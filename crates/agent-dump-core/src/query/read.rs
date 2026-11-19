use crate::output::{i18n::t, render};
use crate::query::{context, text, transcript};
use crate::session::{SessionData, timestamp::Timestamp};
use jiff::civil::Date;
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
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub since: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub until: Option<String>,
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
            since: None,
            until: None,
        }
    }
}

fn parse_iso_date(raw: &str) -> Option<Date> {
    if raw.len() != 10 {
        return None;
    }
    let date: Date = raw.parse().ok()?;
    (date.year() > 0).then_some(date)
}

impl Options {
    fn date_bounds(&self) -> Option<(Option<Date>, Option<Date>)> {
        if self.details && (self.since.is_some() || self.until.is_some()) {
            return None;
        }
        let since = match &self.since {
            Some(raw) => Some(parse_iso_date(raw)?),
            None => None,
        };
        let until = match &self.until {
            Some(raw) => Some(parse_iso_date(raw)?),
            None => None,
        };
        if let (Some(since), Some(until)) = (since, until)
            && since > until
        {
            return None;
        }
        Some((since, until))
    }

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
            && self.date_bounds().is_some()
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
    let (since_date, until_date) = cursor
        .options
        .date_bounds()
        .ok_or_else(|| t("READ_OPTIONS_INVALID", zh, &[]))?;
    let date_filtered = since_date.is_some() || until_date.is_some();
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
                let date = time.map(Timestamp::local_date);
                if date_filtered
                    && !date.is_some_and(|date| {
                        since_date.is_none_or(|since| date >= since)
                            && until_date.is_none_or(|until| date <= until)
                    })
                {
                    continue;
                }
                if !spans.is_empty() {
                    body.push_str("\n\n");
                    offset += 2;
                }
                let start = body.len();
                render::push_safe_body(&mut body, &text);
                let end = offset + body[start..].chars().count();
                spans.push(TextSpan {
                    start: offset,
                    end,
                    date: date.map(|date| date.to_string()),
                });
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::session::{Message, Part, Stats};

    fn millis(iso: &str) -> (i64, String) {
        let ts: Timestamp = iso.parse().unwrap();
        (ts.as_millisecond(), ts.local_date().to_string())
    }

    fn session(messages: Vec<Message>) -> SessionData {
        SessionData {
            extra: serde_json::Map::default(),
            id: "s1".into(),
            title: "t".into(),
            slug: serde_json::Value::Null,
            directory: serde_json::Value::Null,
            version: serde_json::Value::Null,
            time_created: 1,
            time_updated: 1,
            summary_files: serde_json::Value::Null,
            metadata: None,
            stats: Stats {
                message_count: messages.len(),
                ..Stats::default()
            },
            messages,
        }
    }

    #[test]
    fn date_filter_selects_segments_excludes_undated_and_preserves_positions() {
        let (t1, d1) = millis("2026-01-10T12:00:00Z");
        let (t2, d2) = millis("2026-01-14T12:00:00Z");
        let (t3, d3) = millis("2026-01-16T12:00:00Z");
        let (t4, _d4) = millis("2026-01-20T12:00:00Z");
        assert!(d1 < d2 && d2 < d3);

        let mut inferred = Message::new(
            "m3".into(),
            "assistant",
            t2,
            vec![Part::text("inferred-text".into(), t2)],
        );
        inferred.inferred_time = true;

        let data = session(vec![
            Message::new(
                "m1".into(),
                "user",
                t1,
                vec![Part::text("too-early".into(), t1)],
            ),
            Message::new(
                "m2".into(),
                "assistant",
                t2,
                vec![
                    Part::text("early-seg".into(), t1),
                    Part::text("undated-seg".into(), 0),
                    Part::text("keep-one".into(), t2),
                    Part::text("keep-two".into(), t3),
                    Part::text("late-seg".into(), t4),
                ],
            ),
            inferred,
            Message::new(
                "m4".into(),
                "user",
                t3,
                vec![Part::text("in-range-msg".into(), t3)],
            ),
        ]);

        let first = page(
            "codex://s1",
            &data,
            &Request::Start(Options {
                order: Order::Asc,
                max_chars: 10,
                since: Some(d2.clone()),
                until: Some(d3),
                ..Options::default()
            }),
            false,
        )
        .unwrap();

        assert_eq!(first.total_messages, 4);
        assert_eq!(first.messages.len(), 1);
        assert_eq!(first.messages[0].position, 2);
        assert_eq!(first.messages[0].locator, format!("{}:2", first.revision));
        assert_eq!(first.messages[0].text, "keep-one\n\n");
        let spans = first.messages[0].text_spans.as_ref().unwrap();
        assert_eq!(spans.len(), 1);
        assert_eq!(spans[0].date.as_deref(), Some(d2.as_str()));

        let second = page(
            "codex://s1",
            &data,
            &Request::Continue(first.next_cursor.unwrap()),
            false,
        )
        .unwrap();
        assert_eq!(second.messages.len(), 2);
        assert_eq!(second.messages[0].position, 2);
        assert_eq!(second.messages[0].text, "keep-two");
        assert_eq!(second.messages[1].position, 4);
        assert_eq!(second.messages[1].text, "in");

        let third = page(
            "codex://s1",
            &data,
            &Request::Continue(second.next_cursor.unwrap()),
            false,
        )
        .unwrap();
        assert_eq!(third.messages.len(), 1);
        assert_eq!(third.messages[0].position, 4);
        assert_eq!(third.messages[0].text, "-range-msg");
        assert!(third.next_cursor.is_none());
    }

    #[test]
    fn options_omits_unset_dates_and_rejects_invalid_combinations() {
        let value = serde_json::to_value(Options::default()).unwrap();
        let object = value.as_object().unwrap();
        assert!(!object.contains_key("since"));
        assert!(!object.contains_key("until"));

        let legacy: Options = serde_json::from_str(
            r#"{"limit":20,"max_chars":12000,"order":"desc","role":null,"keyword":null,"details":false}"#,
        )
        .unwrap();
        assert!(legacy.since.is_none() && legacy.until.is_none());

        let with_details = Options {
            details: true,
            since: Some("2026-01-14".into()),
            ..Options::default()
        };
        assert!(!with_details.valid());

        let reversed = Options {
            since: Some("2026-01-16".into()),
            until: Some("2026-01-14".into()),
            ..Options::default()
        };
        assert!(!reversed.valid());

        let bad_format = Options {
            since: Some("2026-02-30".into()),
            ..Options::default()
        };
        assert!(!bad_format.valid());
    }
}
