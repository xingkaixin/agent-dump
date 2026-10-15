use crate::providers::contract::{DiagnosticSink, Provider};
use crate::session::{Session, SessionData};
use std::collections::VecDeque;
use std::fmt;
use std::ops::{Deref, DerefMut};
use std::path::PathBuf;
use std::sync::{Arc, Condvar, Mutex, OnceLock};
use std::time::SystemTime;

#[derive(Clone, Debug, PartialEq, Eq)]
struct PathSignal {
    path: PathBuf,
    modified: Option<SystemTime>,
    changed: Option<i128>,
    size: Option<u64>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SessionSignal {
    updated: i64,
    title: String,
    sources: Vec<PathSignal>,
}

impl SessionSignal {
    pub fn signature(&self) -> String {
        let paths: Vec<_> = self
            .sources
            .iter()
            .map(|source| {
                let modified = source.modified.map(|time| {
                    match time.duration_since(SystemTime::UNIX_EPOCH) {
                        Ok(duration) => i128::try_from(duration.as_nanos())
                            .expect("Duration nanoseconds fit in i128"),
                        Err(error) => {
                            -(i128::try_from(error.duration().as_nanos())
                                .expect("Duration nanoseconds fit in i128"))
                        }
                    }
                });
                serde_json::json!([
                    crate::storage::source_io::path_text(&source.path),
                    modified,
                    source.changed,
                    source.size
                ])
            })
            .collect();
        let value = serde_json::json!([
            crate::session::timestamp::Timestamp::from_microsecond(
                self.updated
            )
            .unwrap()
            .iso_utc(),
            paths,
            self.title
        ]);
        let mut encoded = String::new();
        for c in value.to_string().chars() {
            if c.is_ascii() {
                encoded.push(c);
            } else {
                for unit in c.encode_utf16(&mut [0; 2]) {
                    use std::fmt::Write;
                    write!(encoded, "\\u{unit:04x}").unwrap();
                }
            }
        }
        encoded
    }

    pub fn new(provider: &(impl Provider + ?Sized), session: &Session) -> Self {
        let mut sources = Vec::new();
        for path in provider.change_sources(session) {
            if sources
                .iter()
                .any(|signal: &PathSignal| signal.path == path)
            {
                continue;
            }
            let metadata = path.metadata().ok();
            sources.push(PathSignal {
                path,
                modified: metadata
                    .as_ref()
                    .and_then(|metadata| metadata.modified().ok()),
                changed: metadata.as_ref().and_then(changed_time),
                size: metadata.map(|metadata| metadata.len()),
            });
        }
        Self {
            updated: session.updated_at.as_microsecond(),
            title: session.title.clone(),
            sources,
        }
    }
}

#[allow(
    clippy::unnecessary_wraps,
    reason = "The portable counterpart can lack creation timestamps"
)]
#[cfg(unix)]
fn changed_time(metadata: &std::fs::Metadata) -> Option<i128> {
    use std::os::unix::fs::MetadataExt;
    Some(
        i128::from(metadata.ctime()) * 1_000_000_000
            + i128::from(metadata.ctime_nsec()),
    )
}

#[cfg(not(unix))]
fn changed_time(metadata: &std::fs::Metadata) -> Option<i128> {
    let created = metadata.created().ok()?;
    Some(match created.duration_since(SystemTime::UNIX_EPOCH) {
        Ok(duration) => i128::try_from(duration.as_nanos())
            .expect("Duration nanoseconds fit in i128"),
        Err(error) => {
            -(i128::try_from(error.duration().as_nanos())
                .expect("Duration nanoseconds fit in i128"))
        }
    })
}

#[derive(Clone, Debug)]
pub struct SharedReadError(Arc<dyn std::error::Error + Send + Sync>);

impl fmt::Display for SharedReadError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl std::error::Error for SharedReadError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        Some(self.0.as_ref())
    }
}

type Outcome = std::result::Result<Arc<SessionData>, SharedReadError>;

// Serialized JSON bytes: dozens of ordinary sessions fit, while one
// oversized transcript stays with its current consumer only.
const RETAINED_BYTES: usize = 128 << 20;

struct Load {
    identity: (String, String),
    signal: SessionSignal,
    outcome: OnceLock<Outcome>,
    bytes: OnceLock<usize>,
}

struct Entry {
    load: Arc<Load>,
    leases: usize,
    retain: bool,
}

impl Entry {
    fn idle(&self) -> bool {
        self.load.outcome.get().is_some() && self.leases == 0
    }

    fn bytes(&self) -> usize {
        self.load.bytes.get().copied().unwrap_or(0)
    }
}

struct ByteCount(usize);

impl std::io::Write for ByteCount {
    fn write(&mut self, buffer: &[u8]) -> std::io::Result<usize> {
        self.0 += buffer.len();
        Ok(buffer.len())
    }

    fn flush(&mut self) -> std::io::Result<()> {
        Ok(())
    }
}

fn serialized_len(data: &SessionData) -> usize {
    let mut count = ByteCount(0);
    serde_json::to_writer(&mut count, data).map_or(usize::MAX, |()| count.0)
}

pub struct SessionDataCache {
    entries: Mutex<VecDeque<Entry>>,
    ready: Condvar,
    completed_limit: usize,
    byte_limit: usize,
}

impl Default for SessionDataCache {
    fn default() -> Self {
        Self::new(32, RETAINED_BYTES)
    }
}

impl SessionDataCache {
    pub const fn new(completed_limit: usize, byte_limit: usize) -> Self {
        Self {
            entries: Mutex::new(VecDeque::new()),
            ready: Condvar::new(),
            completed_limit,
            byte_limit,
        }
    }

    pub fn get(
        &self,
        name: &str,
        provider: &(impl Provider + ?Sized),
        session: &Session,
        zh: bool,
        diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<Arc<SessionData>> {
        let lease = self.lease(name, provider, session, zh, diagnostics)?;
        lease.load.bytes.get_or_init(|| serialized_len(&lease.data));
        if let Some(entry) = self
            .entries
            .lock()
            .unwrap()
            .iter_mut()
            .find(|entry| Arc::ptr_eq(&entry.load, &lease.load))
        {
            entry.retain = true;
        }
        Ok(lease.data.clone())
    }

    pub fn lease(
        &self,
        name: &str,
        provider: &(impl Provider + ?Sized),
        session: &Session,
        zh: bool,
        diagnostics: &mut DiagnosticSink<'_>,
    ) -> crate::Result<SessionLease<'_>> {
        let identity = (name.to_owned(), session.id.clone());
        let (load, should_load) = loop {
            let signal = SessionSignal::new(provider, session);
            let mut entries = self.entries.lock().unwrap();
            let position = entries
                .iter()
                .position(|entry| entry.load.identity == identity);
            if let Some(position) = position {
                let load = entries[position].load.clone();
                if load.signal != signal && load.outcome.get().is_none() {
                    drop(
                        self.ready
                            .wait_while(entries, |_| {
                                load.outcome.get().is_none()
                            })
                            .unwrap(),
                    );
                    continue;
                }
                let mut entry = entries.remove(position).unwrap();
                if load.signal == signal {
                    entry.leases += 1;
                    entries.push_back(entry);
                    drop(entries);
                    break (load, false);
                }
            }
            let load = Arc::new(Load {
                identity,
                signal,
                outcome: OnceLock::new(),
                bytes: OnceLock::new(),
            });
            entries.push_back(Entry {
                load: load.clone(),
                leases: 1,
                retain: false,
            });
            drop(entries);
            break (load, true);
        };
        if should_load {
            let result =
                std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                    provider.read(session, zh, diagnostics)
                }));
            let (outcome, panic) = match result {
                Ok(result) => (
                    result
                        .map(Arc::new)
                        .map_err(|error| SharedReadError(error.into())),
                    None,
                ),
                Err(panic) => (
                    Err(SharedReadError(
                        crate::Error::from("session reader panicked").into(),
                    )),
                    Some(panic),
                ),
            };
            let mut entries = self.entries.lock().unwrap();
            let failed = outcome.is_err();
            assert!(load.outcome.set(outcome).is_ok());
            if let Some(position) = entries
                .iter()
                .position(|entry| Arc::ptr_eq(&entry.load, &load))
            {
                let entry = entries.remove(position).unwrap();
                if !failed {
                    entries.push_back(entry);
                }
            }
            self.evict(&mut entries);
            self.ready.notify_all();
            drop(entries);
            if let Some(panic) = panic {
                std::panic::resume_unwind(panic);
            }
        } else {
            let entries = self.entries.lock().unwrap();
            drop(
                self.ready
                    .wait_while(entries, |_| load.outcome.get().is_none())
                    .unwrap(),
            );
        }
        match load.outcome.get().unwrap() {
            Ok(data) => Ok(SessionLease {
                cache: self,
                data: data.clone(),
                load,
            }),
            Err(error) => Err(Box::new(error.clone())),
        }
    }

    fn evict(&self, entries: &mut VecDeque<Entry>) {
        entries
            .retain(|entry| !entry.idle() || entry.bytes() <= self.byte_limit);
        let mut completed = entries.iter().filter(|entry| entry.idle()).count();
        let mut bytes: usize = entries
            .iter()
            .filter(|entry| entry.idle())
            .map(Entry::bytes)
            .sum();
        while completed > self.completed_limit || bytes > self.byte_limit {
            let position = entries.iter().position(Entry::idle).unwrap();
            let entry = entries.remove(position).unwrap();
            completed -= 1;
            bytes -= entry.bytes();
        }
    }
}

pub struct SessionLease<'a> {
    cache: &'a SessionDataCache,
    load: Arc<Load>,
    data: Arc<SessionData>,
}

impl Deref for SessionLease<'_> {
    type Target = SessionData;

    fn deref(&self) -> &SessionData {
        &self.data
    }
}

impl DerefMut for SessionLease<'_> {
    fn deref_mut(&mut self) -> &mut SessionData {
        Arc::make_mut(&mut self.data)
    }
}

impl Drop for SessionLease<'_> {
    fn drop(&mut self) {
        let mut entries = self.cache.entries.lock().unwrap();
        if let Some(position) = entries
            .iter()
            .position(|entry| Arc::ptr_eq(&entry.load, &self.load))
        {
            let entry = &mut entries[position];
            entry.leases -= 1;
            if entry.leases == 0 && !entry.retain {
                entries.remove(position);
            }
            self.cache.evict(&mut entries);
        }
        drop(entries);
    }
}

#[cfg(test)]
mod tests;
