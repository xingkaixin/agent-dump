use crate::provider::{Provider, ProviderInfo};

pub struct Registration {
    pub info: ProviderInfo,
    pub open: fn() -> crate::Result<Box<dyn Provider>>,
}

static REGISTRATIONS: &[Registration] = &[
    Registration {
        info: ProviderInfo {
            name: "codex",
            display_name: "Codex",
            scheme: "codex",
            uri_prefixes: &["threads/"],
        },
        open: || Ok(Box::new(crate::codex::Codex::open()?)),
    },
    Registration {
        info: ProviderInfo {
            name: "kimi",
            display_name: "Kimi",
            scheme: "kimi",
            uri_prefixes: &[],
        },
        open: || Ok(Box::new(crate::kimi::Kimi::open()?)),
    },
    Registration {
        info: ProviderInfo {
            name: "claudecode",
            display_name: "Claude Code",
            scheme: "claude",
            uri_prefixes: &[],
        },
        open: || Ok(Box::new(crate::claude::Claude::open()?)),
    },
    Registration {
        info: ProviderInfo {
            name: "pi",
            display_name: "Pi",
            scheme: "pi",
            uri_prefixes: &[],
        },
        open: || Ok(Box::new(crate::pi::Pi::open()?)),
    },
];

pub fn for_name(name: &str) -> crate::Result<&'static Registration> {
    REGISTRATIONS
        .iter()
        .find(|registration| registration.info.name == name)
        .ok_or_else(|| format!("Provider not implemented in Rust: {name}").into())
}

pub fn for_uri(uri: &str) -> crate::Result<(&'static Registration, &str)> {
    let (scheme, mut id) = uri
        .split_once("://")
        .ok_or("Expected a Provider session URI")?;
    let registration = REGISTRATIONS
        .iter()
        .find(|registration| registration.info.scheme == scheme)
        .ok_or_else(|| format!("URI scheme not implemented in Rust: {scheme}"))?;
    for prefix in registration.info.uri_prefixes {
        if let Some(stripped) = id.strip_prefix(prefix) {
            id = stripped;
            break;
        }
    }
    if id.is_empty() {
        return Err("Empty session id".into());
    }
    Ok((registration, id))
}
