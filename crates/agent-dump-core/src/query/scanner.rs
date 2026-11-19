use crate::providers::contract::{
    Discovery, Provider, ProviderInfo, RecoverableDiagnostic, Window,
};
use crate::providers::registry::Registration;
use crate::query::{Query, TimeField};
use crate::session::Session;
use crate::session::timestamp::Timestamp;
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

struct ProviderScan {
    info: &'static ProviderInfo,
    diagnostics: Vec<RecoverableDiagnostic>,
    result: crate::Result<(Box<dyn Provider>, Discovery)>,
}

pub fn discover(
    query: Option<&Query>,
    days: i64,
    time_field: TimeField,
    zh: bool,
    warnings: &mut impl Write,
) -> crate::Result<Scan> {
    discover_registrations(
        crate::providers::registry::all(),
        query,
        days,
        time_field,
        zh,
        warnings,
    )
}

fn discover_registrations(
    registrations: &'static [Registration],
    query: Option<&Query>,
    days: i64,
    time_field: TimeField,
    zh: bool,
    warnings: &mut impl Write,
) -> crate::Result<Scan> {
    let (window, updated_since) = match time_field {
        TimeField::Created => (Window::Created(days), None),
        TimeField::Updated => {
            (Window::Updated(days), Some(Timestamp::days_ago(days)?))
        }
    };
    let selected: Vec<&'static Registration> = registrations
        .iter()
        .filter(|registration| {
            query
                .and_then(|q| q.providers.as_ref())
                .is_none_or(|names| names.contains(registration.info.name))
        })
        .collect();
    let mut scan = Scan::default();
    match selected.as_slice() {
        [] => {}
        [registration] => {
            let result = scan_provider(registration, window);
            record_scan(&mut scan, result, updated_since, zh, warnings)?;
        }
        selected => {
            crate::parallel::ordered(
                selected,
                |registration| scan_provider(registration, window),
                |result| {
                    record_scan(&mut scan, result, updated_since, zh, warnings)
                },
            )?;
        }
    }
    Ok(scan)
}

fn scan_provider(
    registration: &'static Registration,
    window: Window,
) -> ProviderScan {
    let mut diagnostics = Vec::new();
    let result = (registration.open)().and_then(|mut provider| {
        let discovery = provider.discover(window, &mut |diagnostic| {
            diagnostics.push(diagnostic);
            Ok(())
        })?;
        Ok((provider, discovery))
    });
    ProviderScan {
        info: &registration.info,
        diagnostics,
        result,
    }
}

fn record_scan(
    scan: &mut Scan,
    provider_scan: ProviderScan,
    updated_since: Option<Timestamp>,
    zh: bool,
    warnings: &mut impl Write,
) -> crate::Result<()> {
    let ProviderScan {
        info,
        diagnostics,
        result,
    } = provider_scan;
    for diagnostic in diagnostics {
        writeln!(
            warnings,
            "{}",
            crate::output::diagnostics::record_warning(&diagnostic, zh)
        )?;
    }
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
                &crate::providers::error::operation_message(error.as_ref(), zh),
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
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::providers::contract::{DiagnosticSink, Lookup, SessionFailure};
    use crate::session::SessionData;
    use std::collections::BTreeSet;
    use std::path::{Path, PathBuf};
    use std::sync::{Condvar, LazyLock, Mutex};
    use std::thread::{self, ThreadId};
    use std::time::Duration;

    type DiscoverFn = Box<
        dyn FnMut(Window, &mut DiagnosticSink<'_>) -> crate::Result<Discovery>
            + Send
            + Sync,
    >;

    struct StubProvider {
        root: PathBuf,
        discover: DiscoverFn,
    }

    fn stub_provider(
        discover: impl FnMut(
            Window,
            &mut DiagnosticSink<'_>,
        ) -> crate::Result<Discovery>
        + Send
        + Sync
        + 'static,
    ) -> Box<dyn Provider> {
        Box::new(StubProvider {
            root: PathBuf::from("/stub"),
            discover: Box::new(discover),
        })
    }

    impl Provider for StubProvider {
        fn discover(
            &mut self,
            window: Window,
            diagnostics: &mut DiagnosticSink<'_>,
        ) -> crate::Result<Discovery> {
            (self.discover)(window, diagnostics)
        }

        fn find(
            &mut self,
            _id: &str,
            _diagnostics: &mut DiagnosticSink<'_>,
        ) -> crate::Result<Lookup> {
            Ok(Lookup::default())
        }

        fn read(
            &self,
            _session: &Session,
            _zh: bool,
            _diagnostics: &mut DiagnosticSink<'_>,
        ) -> crate::Result<SessionData> {
            Err("unused in scanner tests".into())
        }

        fn source_root(&self) -> &Path {
            &self.root
        }

        fn select_source(&mut self) -> crate::Result<Option<&Path>> {
            Ok(Some(&self.root))
        }

        fn search_roots(&self) -> crate::Result<Vec<(&'static str, PathBuf)>> {
            Ok(vec![("stub", self.root.clone())])
        }
    }

    fn session(
        id: &str,
        created_at: Timestamp,
        updated_at: Timestamp,
    ) -> Session {
        Session {
            id: id.into(),
            title: id.into(),
            created_at,
            updated_at,
            source_path: PathBuf::from(format!("/stub/{id}.jsonl")),
            directory: "/stub".into(),
            version: serde_json::Value::Null,
            model: String::new(),
            project: None,
            message_count: Some(1),
            subtargets: Vec::new(),
            source_metadata: serde_json::Value::Null,
        }
    }

    const fn info(
        name: &'static str,
        display_name: &'static str,
    ) -> ProviderInfo {
        ProviderInfo {
            name,
            display_name,
            scheme: name,
            identifier_label: "<id>",
            uri_prefixes: &[],
        }
    }

    #[test]
    fn parallel_discovery_preserves_order_isolates_failures_and_replays_warnings()
     {
        static STAGE: LazyLock<(Mutex<usize>, Condvar)> =
            LazyLock::new(|| (Mutex::new(0), Condvar::new()));

        fn wait_for_stage(target: usize) {
            let (lock, cvar) = &*STAGE;
            let guard = lock.lock().unwrap();
            let _ = cvar
                .wait_timeout_while(guard, Duration::from_millis(200), |s| {
                    *s < target
                })
                .unwrap();
        }

        fn advance_stage() {
            let (lock, cvar) = &*STAGE;
            *lock.lock().unwrap() += 1;
            cvar.notify_all();
        }

        static REGISTRATIONS: &[Registration] = &[
            Registration {
                info: info("alpha", "Alpha"),
                open: || {
                    Ok(stub_provider(|_window, diagnostics| {
                        wait_for_stage(2);
                        diagnostics(
                            RecoverableDiagnostic::MessageConvertFailed(
                                "alpha-1".into(),
                            ),
                        )?;
                        diagnostics(RecoverableDiagnostic::TitleCacheFailed(
                            "alpha-2".into(),
                        ))?;
                        let now = Timestamp::now();
                        Ok(Discovery {
                            available: true,
                            sessions: vec![session("a-1", now, now)],
                            failures: vec![SessionFailure {
                                source: "/stub/a-bad.jsonl".into(),
                                error: "bad alpha".into(),
                            }],
                        })
                    }))
                },
            },
            Registration {
                info: info("beta", "Beta"),
                open: || {
                    Ok(stub_provider(|_window, diagnostics| {
                        wait_for_stage(1);
                        diagnostics(
                            RecoverableDiagnostic::MessageDataParseFailed(
                                "beta-1".into(),
                            ),
                        )?;
                        advance_stage();
                        Err("discover boom".into())
                    }))
                },
            },
            Registration {
                info: info("gamma", "Gamma"),
                open: || Err("open boom".into()),
            },
            Registration {
                info: info("delta", "Delta"),
                open: || {
                    Ok(stub_provider(|_window, diagnostics| {
                        diagnostics(
                            RecoverableDiagnostic::PartDataParseFailed(
                                "delta-1".into(),
                            ),
                        )?;
                        Ok(Discovery::default())
                    }))
                },
            },
            Registration {
                info: info("epsilon", "Epsilon"),
                open: || {
                    Ok(stub_provider(|_window, diagnostics| {
                        diagnostics(
                            RecoverableDiagnostic::MessageConvertFailed(
                                "epsilon-1".into(),
                            ),
                        )?;
                        advance_stage();
                        let now = Timestamp::now();
                        Ok(Discovery::available(vec![session("e-1", now, now)]))
                    }))
                },
            },
        ];

        *STAGE.0.lock().unwrap() = 0;
        let mut warnings = Vec::new();
        let scan = discover_registrations(
            REGISTRATIONS,
            None,
            7,
            TimeField::Created,
            false,
            &mut warnings,
        )
        .unwrap();

        let group_names: Vec<_> =
            scan.groups.iter().map(|group| group.info.name).collect();
        assert_eq!(group_names, vec!["alpha", "epsilon"]);
        assert_eq!(scan.groups[0].sessions[0].id, "a-1");
        assert_eq!(scan.groups[1].sessions[0].id, "e-1");
        assert_eq!(scan.failed_providers, vec!["alpha", "beta", "gamma"]);

        let warning_text = String::from_utf8(warnings).unwrap();
        let lines: Vec<_> = warning_text.lines().collect();
        assert_eq!(
            lines,
            vec![
                "⚠️  Failed to convert message format: alpha-1",
                "⚠️  Failed to load title cache: alpha-2",
                "⚠️  Failed to parse session file /stub/a-bad.jsonl: bad alpha",
                "⚠️  Failed to parse message data message=beta-1",
                "⚠️  Beta provider operation failed: discover boom",
                "⚠️  Gamma provider operation failed: open boom",
                "⚠️  Failed to parse message part data part=delta-1",
                "⚠️  Failed to convert message format: epsilon-1",
            ]
        );
    }

    #[test]
    fn single_provider_runs_directly_without_spawning_threads() {
        static CALLS: LazyLock<Mutex<Vec<(&'static str, ThreadId)>>> =
            LazyLock::new(|| Mutex::new(Vec::new()));

        static REGISTRATIONS: &[Registration] = &[
            Registration {
                info: info("alpha", "Alpha"),
                open: || {
                    CALLS
                        .lock()
                        .unwrap()
                        .push(("alpha", thread::current().id()));
                    Ok(stub_provider(|_, _| Ok(Discovery::default())))
                },
            },
            Registration {
                info: info("beta", "Beta"),
                open: || {
                    CALLS
                        .lock()
                        .unwrap()
                        .push(("beta-open", thread::current().id()));
                    Ok(stub_provider(|_, diagnostics| {
                        CALLS
                            .lock()
                            .unwrap()
                            .push(("beta-discover", thread::current().id()));
                        diagnostics(RecoverableDiagnostic::TitleCacheFailed(
                            "beta-cache".into(),
                        ))?;
                        let now = Timestamp::now();
                        Ok(Discovery::available(vec![session("b-1", now, now)]))
                    }))
                },
            },
        ];

        CALLS.lock().unwrap().clear();
        let query = Query {
            providers: Some(BTreeSet::from(["beta".to_owned()])),
            ..Query::default()
        };
        let mut warnings = Vec::new();
        let scan = discover_registrations(
            REGISTRATIONS,
            Some(&query),
            7,
            TimeField::Created,
            true,
            &mut warnings,
        )
        .unwrap();

        let caller = thread::current().id();
        assert_eq!(
            *CALLS.lock().unwrap(),
            vec![("beta-open", caller), ("beta-discover", caller)]
        );
        assert_eq!(scan.groups.len(), 1);
        assert_eq!(scan.groups[0].info.name, "beta");
        assert!(scan.failed_providers.is_empty());
        assert_eq!(
            String::from_utf8(warnings).unwrap(),
            "警告: 加载标题缓存失败: beta-cache\n"
        );
    }

    #[test]
    fn zero_selected_providers_skips_opening_any_provider() {
        static OPENED: LazyLock<Mutex<usize>> = LazyLock::new(|| Mutex::new(0));

        static REGISTRATIONS: &[Registration] = &[Registration {
            info: info("alpha", "Alpha"),
            open: || {
                *OPENED.lock().unwrap() += 1;
                Ok(stub_provider(|_, _| Ok(Discovery::default())))
            },
        }];

        *OPENED.lock().unwrap() = 0;
        let query = Query {
            providers: Some(BTreeSet::from(["other".to_owned()])),
            ..Query::default()
        };
        let mut warnings = Vec::new();
        let scan = discover_registrations(
            REGISTRATIONS,
            Some(&query),
            7,
            TimeField::Created,
            false,
            &mut warnings,
        )
        .unwrap();

        assert_eq!(*OPENED.lock().unwrap(), 0);
        assert!(scan.groups.is_empty());
        assert!(scan.failed_providers.is_empty());
        assert!(warnings.is_empty());
    }

    #[test]
    fn updated_time_field_filters_stale_sessions_in_parallel() {
        static REGISTRATIONS: &[Registration] = &[
            Registration {
                info: info("alpha", "Alpha"),
                open: || {
                    Ok(stub_provider(|window, _| {
                        assert_eq!(window, Window::Updated(7));
                        let now = Timestamp::now();
                        let stale = Timestamp::days_ago(30)?;
                        Ok(Discovery::available(vec![
                            session("fresh", now, now),
                            session("stale", stale, stale),
                        ]))
                    }))
                },
            },
            Registration {
                info: info("beta", "Beta"),
                open: || {
                    Ok(stub_provider(|window, _| {
                        assert_eq!(window, Window::Updated(7));
                        let stale = Timestamp::days_ago(30)?;
                        Ok(Discovery::available(vec![session(
                            "old-only", stale, stale,
                        )]))
                    }))
                },
            },
        ];

        let mut warnings = Vec::new();
        let scan = discover_registrations(
            REGISTRATIONS,
            None,
            7,
            TimeField::Updated,
            false,
            &mut warnings,
        )
        .unwrap();

        assert_eq!(scan.groups.len(), 2);
        assert_eq!(scan.groups[0].info.name, "alpha");
        let alpha_ids: Vec<_> = scan.groups[0]
            .sessions
            .iter()
            .map(|s| s.id.as_str())
            .collect();
        assert_eq!(alpha_ids, vec!["fresh"]);
        assert_eq!(scan.groups[1].info.name, "beta");
        assert!(scan.groups[1].sessions.is_empty());
        assert!(warnings.is_empty());
    }
}
