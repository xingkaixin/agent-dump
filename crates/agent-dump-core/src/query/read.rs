use crate::output::{i18n::t, render};
use crate::query::{context, text, transcript};
use crate::session::SessionData;
use serde::{Deserialize, Serialize};
use std::fmt::Write;

#[derive(Clone, Copy, Default, Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Order {
    Asc,
    #[default]
    Desc,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Options {
    pub limit: u32,
    pub max_chars: u32,
    pub order: Order,
    pub role: Option<String>,
    pub keyword: Option<String>,
    pub details: bool,
}

impl Default for Options {
    fn default() -> Self {
        Self {
            limit: 20,
            max_chars: 12_000,
            order: Order::Desc,
            role: None,
            keyword: None,
            details: false,
        }
    }
}

impl Options {
    fn valid(&self) -> bool {
        (1..=100).contains(&self.limit)
            && (1..=100_000).contains(&self.max_chars)
            && self
                .role
                .as_ref()
                .is_none_or(|s| !s.trim().is_empty() && s.len() <= 100)
            && self.keyword.as_ref().is_none_or(|s| {
                !text::normalize(s).is_empty() && s.len() <= 4096
            })
    }
}

pub enum Request {
    Start(Options),
    Continue(String),
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Cursor {
    uri: String,
    revision: String,
    options: Options,
    position: usize,
    offset: usize,
}

impl Cursor {
    fn decode(raw: &str) -> Option<Self> {
        let raw = raw.strip_prefix("r1.")?;
        // Allow escaped URI/filter text while bounding untrusted allocations.
        if raw.len() > 131_072 || raw.len() % 2 != 0 {
            return None;
        }
        let bytes: Option<Vec<_>> = raw
            .as_bytes()
            .as_chunks::<2>()
            .0
            .iter()
            .map(|pair| {
                u8::from_str_radix(std::str::from_utf8(pair).ok()?, 16).ok()
            })
            .collect();
        serde_json::from_slice(&bytes?).ok()
    }

    fn encode(&self) -> crate::Result<String> {
        let mut value = String::from("r1.");
        for byte in serde_json::to_vec(self)? {
            write!(value, "{byte:02x}")?;
        }
        Ok(value)
    }

    const fn advance(&mut self) {
        self.position = match self.options.order {
            Order::Asc => self.position + 1,
            Order::Desc => self.position - 1,
        };
        self.offset = 0;
    }
}

#[derive(Serialize)]
pub struct TextSpan {
    pub start: usize,
    pub end: usize,
    pub date: Option<String>,
}

#[derive(Serialize)]
pub struct Fragment {
    pub position: usize,
    pub locator: String,
    pub role: String,
    pub text: String,
    pub start: usize,
    pub end: usize,
    pub total_chars: usize,
    pub truncated: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub text_spans: Option<Vec<TextSpan>>,
}

#[derive(Serialize)]
pub struct Page {
    pub uri: String,
    pub revision: String,
    pub total_messages: usize,
    pub options: Options,
    pub messages: Vec<Fragment>,
    pub next_cursor: Option<String>,
}

pub fn page(
    uri: &str,
    data: &SessionData,
    request: &Request,
    zh: bool,
) -> crate::Result<Page> {
    let revision = context::revision(data)?;
    let mut cursor = match request {
        Request::Start(options) => Cursor {
            uri: uri.into(),
            revision: revision.clone(),
            position: match options.order {
                Order::Asc => 1,
                Order::Desc => data.messages.len(),
            },
            offset: 0,
            options: options.clone(),
        },
        Request::Continue(raw) => {
            let cursor = Cursor::decode(raw)
                .ok_or_else(|| t("READ_CURSOR_INVALID", zh, &[]))?;
            if cursor.uri != uri || cursor.revision != revision {
                return Err(t("READ_CURSOR_STALE", zh, &[]).into());
            }
            if !(1..=data.messages.len()).contains(&cursor.position) {
                return Err(t("READ_CURSOR_INVALID", zh, &[]).into());
            }
            cursor
        }
    };
    if uri.len() > 4096 || !cursor.options.valid() {
        return Err(t("READ_OPTIONS_INVALID", zh, &[]).into());
    }
    let matcher = cursor
        .options
        .keyword
        .as_ref()
        .map(|s| text::TextQuery::new(s, text::Mode::Phrase));
    let mut remaining = cursor.options.max_chars as usize;
    let mut messages = Vec::new();
    let mut next_cursor = None;
    while (1..=data.messages.len()).contains(&cursor.position) {
        let message = &data.messages[cursor.position - 1];
        if cursor
            .options
            .role
            .as_ref()
            .is_some_and(|role| role != &message.role)
        {
            if cursor.offset != 0 {
                return Err(t("READ_CURSOR_INVALID", zh, &[]).into());
            }
            cursor.advance();
            continue;
        }
        let (body, spans) = if cursor.options.details {
            (render::reader_message(message, true), None)
        } else {
            let mut body = String::new();
            let mut spans = Vec::new();
            let mut offset = 0;
            for (text, time) in transcript::visible_segments(message) {
                if !spans.is_empty() {
                    body.push_str("\n\n");
                    offset += 2;
                }
                let text = render::safe_body(&text);
                let end = offset + text.chars().count();
                spans.push(TextSpan {
                    start: offset,
                    end,
                    date: time.map(|time| time.local_date().to_string()),
                });
                body.push_str(&text);
                offset = end;
            }
            (body, Some(spans))
        };
        if body.is_empty()
            || matcher.as_ref().is_some_and(|m| m.find(&[&body]).is_none())
        {
            if cursor.offset != 0 {
                return Err(t("READ_CURSOR_INVALID", zh, &[]).into());
            }
            cursor.advance();
            continue;
        }
        let total_chars = body.chars().count();
        if cursor.offset >= total_chars {
            return Err(t("READ_CURSOR_INVALID", zh, &[]).into());
        }
        if remaining == 0 || messages.len() >= cursor.options.limit as usize {
            next_cursor = Some(cursor.encode()?);
            break;
        }
        let text: String =
            body.chars().skip(cursor.offset).take(remaining).collect();
        let length = text.chars().count();
        let end = cursor.offset + length;
        messages.push(Fragment {
            position: cursor.position,
            locator: format!("{revision}:{}", cursor.position),
            role: message.role.clone(),
            text,
            start: cursor.offset,
            end,
            total_chars,
            truncated: cursor.offset != 0 || end < total_chars,
            text_spans: spans.map(|spans| {
                spans
                    .into_iter()
                    .filter_map(|span| {
                        let start = span.start.max(cursor.offset);
                        let stop = span.end.min(end);
                        (start < stop).then_some(TextSpan {
                            start,
                            end: stop,
                            date: span.date,
                        })
                    })
                    .collect()
            }),
        });
        remaining -= length;
        if end < total_chars {
            cursor.offset = end;
            next_cursor = Some(cursor.encode()?);
            break;
        }
        cursor.advance();
    }
    Ok(Page {
        uri: cursor.uri,
        revision,
        total_messages: data.messages.len(),
        options: cursor.options,
        messages,
        next_cursor,
    })
}
