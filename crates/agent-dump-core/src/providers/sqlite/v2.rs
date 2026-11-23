use crate::compat::value::{
    add_integer, float, integer, integer_number, json_object, string, text,
};
use crate::providers::sqlite::Facts;
use crate::session::{
    ImagePart, Message, Part, Session, SessionData, Stats, TextPart, ToolPart,
};
use rusqlite::{Connection, ToSql, types::ValueRef};
use serde_json::{Map, Value, json};
use std::collections::{HashMap, HashSet};

pub fn read(
    connection: &Connection,
    session: &Session,
    row: &Value,
) -> crate::Result<SessionData> {
    let mut stmt = connection.prepare(
        "SELECT id, type, seq, time_created, data FROM session_message \
         WHERE session_id = ? ORDER BY seq ASC",
    )?;
    let mut rows = stmt.query([&session.id])?;
    let mut messages = Vec::new();
    while let Some(r) = rows.next()? {
        if let Some(msg) = decode_sqlite_row(r)? {
            messages.push(msg);
        }
    }
    let current = crate::providers::sqlite::build_session(
        row,
        &session.source_path,
        true,
        Some(&Facts {
            count: messages.len(),
            title: crate::providers::sqlite::user_title(&messages),
        }),
    );
    let mut input = integer_number(&row["tokens_input"]);
    add_integer(&mut input, &row["tokens_cache_read"]);
    add_integer(&mut input, &row["tokens_cache_write"]);
    let mut output = integer_number(&row["tokens_output"]);
    add_integer(&mut output, &row["tokens_reasoning"]);
    let mut total = input.clone();
    add_integer(&mut total, &output.clone().into());
    let stats = Stats {
        total_cost: serde_json::Number::from_f64(float(&row["cost"])).unwrap(),
        total_input_tokens: input,
        total_output_tokens: output,
        message_count: messages.len(),
        total_tokens: Some(total),
        extra: Map::default(),
    };
    let mut payload = current.payload(messages, stats);
    payload.slug = row["slug"].clone();
    payload.directory = row["directory"].clone();
    payload.time_created = integer(&row["time_created"]);
    payload.time_updated = integer(&row["time_updated"]);
    payload.summary_files = row["summary_files"].clone();
    let mut metadata = row.as_object().unwrap().clone();
    for name in ["model", "metadata", "revert", "fork_boundary"] {
        if let Some(value) = metadata.get_mut(name) {
            *value = json_object(value).unwrap_or(Value::Null);
        }
    }
    payload.metadata = Some(metadata.into());
    Ok(payload)
}

fn value_from_ref(value: ValueRef<'_>) -> crate::Result<Value> {
    Ok(match value {
        ValueRef::Null => Value::Null,
        ValueRef::Integer(v) => v.into(),
        ValueRef::Real(v) => crate::compat::json::float(v).into(),
        ValueRef::Text(v) => std::str::from_utf8(v)?.into(),
        ValueRef::Blob(bytes) => {
            bytes.iter().copied().map(Value::from).collect()
        }
    })
}

fn json_from_ref(value: ValueRef<'_>) -> crate::Result<Value> {
    match value {
        ValueRef::Text(bytes) => crate::compat::json::from_slice(bytes),
        ValueRef::Blob(bytes) => crate::compat::json::from_bytes(bytes),
        other => {
            let val = value_from_ref(other)?;
            Err(crate::providers::error::ProviderError::Cause {
                kind: "TypeError",
                message: format!(
                    "the JSON object must be str, bytes or bytearray, not {}",
                    crate::compat::value::type_name(&val)
                ),
            }
            .into())
        }
    }
}

fn decode_sqlite_row(r: &rusqlite::Row<'_>) -> crate::Result<Option<Message>> {
    let id_val = value_from_ref(r.get_ref(0)?)?;
    let id_str = string(&id_val);
    let kind_val = value_from_ref(r.get_ref(1)?)?;
    let seq_val = value_from_ref(r.get_ref(2)?)?;
    let time_val = value_from_ref(r.get_ref(3)?)?;
    let data = json_from_ref(r.get_ref(4)?).map_err(|error| {
        crate::providers::error::ProviderError::invalid(format!(
            "Invalid OpenCode V2 message {id_str}: {error}"
        ))
    })?;
    message_from_parts(id_str, kind_val, seq_val, &time_val, data).map_err(
        |error| {
            crate::providers::error::ProviderError::invalid(format!(
                "Invalid OpenCode V2 message {}: {error}",
                string(&id_val)
            ))
            .into()
        },
    )
}

enum FastFact {
    Count { title: Option<String> },
    Skip,
    Fallback,
}

fn is_non_empty_clean(s: &str) -> bool {
    if !s.contains('<') {
        return s.bytes().any(|b| !b.is_ascii_whitespace())
            && !s.trim().is_empty();
    }
    !crate::providers::text::clean(s).is_empty()
}

struct PositiveNumberVisitor;
impl<'de> serde::de::Visitor<'de> for PositiveNumberVisitor {
    type Value = bool;
    fn expecting(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("any JSON value")
    }
    fn visit_i64<E>(self, v: i64) -> Result<bool, E> {
        Ok(v > 0)
    }
    fn visit_u64<E>(self, v: u64) -> Result<bool, E> {
        Ok(v > 0)
    }
    fn visit_f64<E>(self, v: f64) -> Result<bool, E> {
        Ok(v > 0.0)
    }
    fn visit_bool<E>(self, _: bool) -> Result<bool, E> {
        Ok(false)
    }
    fn visit_str<E>(self, _: &str) -> Result<bool, E> {
        Ok(false)
    }
    fn visit_unit<E>(self) -> Result<bool, E> {
        Ok(false)
    }
    fn visit_none<E>(self) -> Result<bool, E> {
        Ok(false)
    }
    fn visit_seq<A: serde::de::SeqAccess<'de>>(
        self,
        mut seq: A,
    ) -> Result<bool, A::Error> {
        while seq.next_element::<serde::de::IgnoredAny>()?.is_some() {}
        Ok(false)
    }
    fn visit_map<A: serde::de::MapAccess<'de>>(
        self,
        mut map: A,
    ) -> Result<bool, A::Error> {
        let mut positive = false;
        let mut entries = 0usize;
        while let Some(key) = map.next_key::<std::borrow::Cow<'de, str>>()? {
            entries += 1;
            if entries == 1 && key == "$serde_json::private::Number" {
                let raw = map.next_value::<std::borrow::Cow<'de, str>>()?;
                positive =
                    raw.parse::<f64>().is_ok_and(|n| n.is_finite() && n > 0.0);
            } else {
                positive = false;
                map.next_value::<serde::de::IgnoredAny>()?;
            }
        }
        Ok(entries == 1 && positive)
    }
}

struct PositiveSeed;
impl<'de> serde::de::DeserializeSeed<'de> for PositiveSeed {
    type Value = bool;
    fn deserialize<D: serde::Deserializer<'de>>(
        self,
        deserializer: D,
    ) -> Result<bool, D::Error> {
        deserializer.deserialize_any(PositiveNumberVisitor)
    }
}

struct TokensSeed;
impl<'de> serde::de::DeserializeSeed<'de> for TokensSeed {
    type Value = bool;
    fn deserialize<D: serde::Deserializer<'de>>(
        self,
        deserializer: D,
    ) -> Result<bool, D::Error> {
        struct CacheSeed;
        impl<'de> serde::de::DeserializeSeed<'de> for CacheSeed {
            type Value = bool;
            fn deserialize<D: serde::Deserializer<'de>>(
                self,
                deserializer: D,
            ) -> Result<bool, D::Error> {
                struct V;
                impl<'de> serde::de::Visitor<'de> for V {
                    type Value = bool;
                    fn expecting(
                        &self,
                        f: &mut std::fmt::Formatter<'_>,
                    ) -> std::fmt::Result {
                        f.write_str("any JSON value")
                    }
                    fn visit_map<A: serde::de::MapAccess<'de>>(
                        self,
                        mut map: A,
                    ) -> Result<bool, A::Error> {
                        let mut pos = false;
                        while let Some(k) =
                            map.next_key::<std::borrow::Cow<'de, str>>()?
                        {
                            if matches!(k.as_ref(), "read" | "write") {
                                pos |= map.next_value_seed(PositiveSeed)?;
                            } else {
                                map.next_value::<serde::de::IgnoredAny>()?;
                            }
                        }
                        Ok(pos)
                    }
                    fn visit_bool<E>(self, _: bool) -> Result<bool, E> {
                        Ok(false)
                    }
                    fn visit_i64<E>(self, _: i64) -> Result<bool, E> {
                        Ok(false)
                    }
                    fn visit_u64<E>(self, _: u64) -> Result<bool, E> {
                        Ok(false)
                    }
                    fn visit_f64<E>(self, _: f64) -> Result<bool, E> {
                        Ok(false)
                    }
                    fn visit_str<E>(self, _: &str) -> Result<bool, E> {
                        Ok(false)
                    }
                    fn visit_unit<E>(self) -> Result<bool, E> {
                        Ok(false)
                    }
                    fn visit_none<E>(self) -> Result<bool, E> {
                        Ok(false)
                    }
                    fn visit_seq<A: serde::de::SeqAccess<'de>>(
                        self,
                        mut seq: A,
                    ) -> Result<bool, A::Error> {
                        while seq
                            .next_element::<serde::de::IgnoredAny>()?
                            .is_some()
                        {}
                        Ok(false)
                    }
                }
                deserializer.deserialize_any(V)
            }
        }
        struct V;
        impl<'de> serde::de::Visitor<'de> for V {
            type Value = bool;
            fn expecting(
                &self,
                f: &mut std::fmt::Formatter<'_>,
            ) -> std::fmt::Result {
                f.write_str("any JSON value")
            }
            fn visit_map<A: serde::de::MapAccess<'de>>(
                self,
                mut map: A,
            ) -> Result<bool, A::Error> {
                let mut pos = false;
                while let Some(k) =
                    map.next_key::<std::borrow::Cow<'de, str>>()?
                {
                    match k.as_ref() {
                        "input" | "output" | "reasoning" => {
                            pos |= map.next_value_seed(PositiveSeed)?;
                        }
                        "cache" => {
                            pos |= map.next_value_seed(CacheSeed)?;
                        }
                        _ => {
                            map.next_value::<serde::de::IgnoredAny>()?;
                        }
                    }
                }
                Ok(pos)
            }
            fn visit_bool<E>(self, _: bool) -> Result<bool, E> {
                Ok(false)
            }
            fn visit_i64<E>(self, _: i64) -> Result<bool, E> {
                Ok(false)
            }
            fn visit_u64<E>(self, _: u64) -> Result<bool, E> {
                Ok(false)
            }
            fn visit_f64<E>(self, _: f64) -> Result<bool, E> {
                Ok(false)
            }
            fn visit_str<E>(self, _: &str) -> Result<bool, E> {
                Ok(false)
            }
            fn visit_unit<E>(self) -> Result<bool, E> {
                Ok(false)
            }
            fn visit_none<E>(self) -> Result<bool, E> {
                Ok(false)
            }
            fn visit_seq<A: serde::de::SeqAccess<'de>>(
                self,
                mut seq: A,
            ) -> Result<bool, A::Error> {
                while seq.next_element::<serde::de::IgnoredAny>()?.is_some() {}
                Ok(false)
            }
        }
        deserializer.deserialize_any(V)
    }
}

struct NonNullSeed;
impl<'de> serde::de::DeserializeSeed<'de> for NonNullSeed {
    type Value = bool;
    fn deserialize<D: serde::Deserializer<'de>>(
        self,
        deserializer: D,
    ) -> Result<bool, D::Error> {
        struct V;
        impl<'de> serde::de::Visitor<'de> for V {
            type Value = bool;
            fn expecting(
                &self,
                f: &mut std::fmt::Formatter<'_>,
            ) -> std::fmt::Result {
                f.write_str("any JSON value")
            }
            fn visit_unit<E>(self) -> Result<bool, E> {
                Ok(false)
            }
            fn visit_none<E>(self) -> Result<bool, E> {
                Ok(false)
            }
            fn visit_bool<E>(self, _: bool) -> Result<bool, E> {
                Ok(true)
            }
            fn visit_i64<E>(self, _: i64) -> Result<bool, E> {
                Ok(true)
            }
            fn visit_u64<E>(self, _: u64) -> Result<bool, E> {
                Ok(true)
            }
            fn visit_f64<E>(self, _: f64) -> Result<bool, E> {
                Ok(true)
            }
            fn visit_str<E>(self, _: &str) -> Result<bool, E> {
                Ok(true)
            }
            fn visit_seq<A: serde::de::SeqAccess<'de>>(
                self,
                mut seq: A,
            ) -> Result<bool, A::Error> {
                while seq.next_element::<serde::de::IgnoredAny>()?.is_some() {}
                Ok(true)
            }
            fn visit_map<A: serde::de::MapAccess<'de>>(
                self,
                mut map: A,
            ) -> Result<bool, A::Error> {
                while map
                    .next_entry::<serde::de::IgnoredAny, serde::de::IgnoredAny>(
                    )?
                    .is_some()
                {}
                Ok(true)
            }
        }
        deserializer.deserialize_any(V)
    }
}

struct NonEmptyArraySeed;
impl<'de> serde::de::DeserializeSeed<'de> for NonEmptyArraySeed {
    type Value = bool;
    fn deserialize<D: serde::Deserializer<'de>>(
        self,
        deserializer: D,
    ) -> Result<bool, D::Error> {
        struct V;
        impl<'de> serde::de::Visitor<'de> for V {
            type Value = bool;
            fn expecting(
                &self,
                f: &mut std::fmt::Formatter<'_>,
            ) -> std::fmt::Result {
                f.write_str("any JSON value")
            }
            fn visit_seq<A: serde::de::SeqAccess<'de>>(
                self,
                mut seq: A,
            ) -> Result<bool, A::Error> {
                let mut any = false;
                while seq.next_element::<serde::de::IgnoredAny>()?.is_some() {
                    any = true;
                }
                Ok(any)
            }
            fn visit_bool<E>(self, _: bool) -> Result<bool, E> {
                Ok(false)
            }
            fn visit_i64<E>(self, _: i64) -> Result<bool, E> {
                Ok(false)
            }
            fn visit_u64<E>(self, _: u64) -> Result<bool, E> {
                Ok(false)
            }
            fn visit_f64<E>(self, _: f64) -> Result<bool, E> {
                Ok(false)
            }
            fn visit_str<E>(self, _: &str) -> Result<bool, E> {
                Ok(false)
            }
            fn visit_unit<E>(self) -> Result<bool, E> {
                Ok(false)
            }
            fn visit_none<E>(self) -> Result<bool, E> {
                Ok(false)
            }
            fn visit_map<A: serde::de::MapAccess<'de>>(
                self,
                mut map: A,
            ) -> Result<bool, A::Error> {
                while map
                    .next_entry::<serde::de::IgnoredAny, serde::de::IgnoredAny>(
                    )?
                    .is_some()
                {}
                Ok(false)
            }
        }
        deserializer.deserialize_any(V)
    }
}

struct OptStrSeed;
impl<'de> serde::de::DeserializeSeed<'de> for OptStrSeed {
    type Value = Option<std::borrow::Cow<'de, str>>;
    fn deserialize<D: serde::Deserializer<'de>>(
        self,
        deserializer: D,
    ) -> Result<Self::Value, D::Error> {
        struct V;
        impl<'de> serde::de::Visitor<'de> for V {
            type Value = Option<std::borrow::Cow<'de, str>>;
            fn expecting(
                &self,
                f: &mut std::fmt::Formatter<'_>,
            ) -> std::fmt::Result {
                f.write_str("any JSON value")
            }
            fn visit_borrowed_str<E>(
                self,
                v: &'de str,
            ) -> Result<Self::Value, E> {
                Ok(Some(std::borrow::Cow::Borrowed(v)))
            }
            fn visit_str<E>(self, v: &str) -> Result<Self::Value, E> {
                Ok(Some(std::borrow::Cow::Owned(v.to_owned())))
            }
            fn visit_string<E>(self, v: String) -> Result<Self::Value, E> {
                Ok(Some(std::borrow::Cow::Owned(v)))
            }
            fn visit_bool<E>(self, _: bool) -> Result<Self::Value, E> {
                Ok(None)
            }
            fn visit_i64<E>(self, _: i64) -> Result<Self::Value, E> {
                Ok(None)
            }
            fn visit_u64<E>(self, _: u64) -> Result<Self::Value, E> {
                Ok(None)
            }
            fn visit_f64<E>(self, _: f64) -> Result<Self::Value, E> {
                Ok(None)
            }
            fn visit_unit<E>(self) -> Result<Self::Value, E> {
                Ok(None)
            }
            fn visit_none<E>(self) -> Result<Self::Value, E> {
                Ok(None)
            }
            fn visit_seq<A: serde::de::SeqAccess<'de>>(
                self,
                mut seq: A,
            ) -> Result<Self::Value, A::Error> {
                while seq.next_element::<serde::de::IgnoredAny>()?.is_some() {}
                Ok(None)
            }
            fn visit_map<A: serde::de::MapAccess<'de>>(
                self,
                mut map: A,
            ) -> Result<Self::Value, A::Error> {
                while map
                    .next_entry::<serde::de::IgnoredAny, serde::de::IgnoredAny>(
                    )?
                    .is_some()
                {}
                Ok(None)
            }
        }
        deserializer.deserialize_any(V)
    }
}

struct AssistantContentItemSeed;
impl<'de> serde::de::DeserializeSeed<'de> for AssistantContentItemSeed {
    type Value = bool;
    fn deserialize<D: serde::Deserializer<'de>>(
        self,
        deserializer: D,
    ) -> Result<bool, D::Error> {
        struct V;
        impl<'de> serde::de::Visitor<'de> for V {
            type Value = bool;
            fn expecting(
                &self,
                f: &mut std::fmt::Formatter<'_>,
            ) -> std::fmt::Result {
                f.write_str("any JSON value")
            }
            fn visit_map<A: serde::de::MapAccess<'de>>(
                self,
                mut map: A,
            ) -> Result<bool, A::Error> {
                let mut kind: Option<std::borrow::Cow<'de, str>> = None;
                let mut text_non_empty = false;
                let mut name_non_empty = false;
                while let Some(k) =
                    map.next_key::<std::borrow::Cow<'de, str>>()?
                {
                    match k.as_ref() {
                        "type" => {
                            kind = map.next_value_seed(OptStrSeed)?;
                        }
                        "text" => {
                            if let Some(s) = map.next_value_seed(OptStrSeed)? {
                                text_non_empty = is_non_empty_clean(&s);
                            }
                        }
                        "name" => {
                            if let Some(s) = map.next_value_seed(OptStrSeed)? {
                                name_non_empty = !s.is_empty();
                            }
                        }
                        _ => {
                            map.next_value::<serde::de::IgnoredAny>()?;
                        }
                    }
                }
                Ok(match kind.as_deref() {
                    Some("text" | "reasoning") => text_non_empty,
                    Some("tool") if name_non_empty => true,
                    _ => true,
                })
            }
            fn visit_bool<E>(self, _: bool) -> Result<bool, E> {
                Ok(true)
            }
            fn visit_i64<E>(self, _: i64) -> Result<bool, E> {
                Ok(true)
            }
            fn visit_u64<E>(self, _: u64) -> Result<bool, E> {
                Ok(true)
            }
            fn visit_f64<E>(self, _: f64) -> Result<bool, E> {
                Ok(true)
            }
            fn visit_str<E>(self, _: &str) -> Result<bool, E> {
                Ok(true)
            }
            fn visit_unit<E>(self) -> Result<bool, E> {
                Ok(true)
            }
            fn visit_none<E>(self) -> Result<bool, E> {
                Ok(true)
            }
            fn visit_seq<A: serde::de::SeqAccess<'de>>(
                self,
                mut seq: A,
            ) -> Result<bool, A::Error> {
                while seq.next_element::<serde::de::IgnoredAny>()?.is_some() {}
                Ok(true)
            }
        }
        deserializer.deserialize_any(V)
    }
}

struct AssistantContentSeed;
impl<'de> serde::de::DeserializeSeed<'de> for AssistantContentSeed {
    type Value = Option<bool>;
    fn deserialize<D: serde::Deserializer<'de>>(
        self,
        deserializer: D,
    ) -> Result<Option<bool>, D::Error> {
        struct V;
        impl<'de> serde::de::Visitor<'de> for V {
            type Value = Option<bool>;
            fn expecting(
                &self,
                f: &mut std::fmt::Formatter<'_>,
            ) -> std::fmt::Result {
                f.write_str("any JSON value")
            }
            fn visit_seq<A: serde::de::SeqAccess<'de>>(
                self,
                mut seq: A,
            ) -> Result<Option<bool>, A::Error> {
                let mut visible = false;
                while let Some(item) =
                    seq.next_element_seed(AssistantContentItemSeed)?
                {
                    visible |= item;
                }
                Ok(Some(visible))
            }
            fn visit_bool<E>(self, _: bool) -> Result<Option<bool>, E> {
                Ok(None)
            }
            fn visit_i64<E>(self, _: i64) -> Result<Option<bool>, E> {
                Ok(None)
            }
            fn visit_u64<E>(self, _: u64) -> Result<Option<bool>, E> {
                Ok(None)
            }
            fn visit_f64<E>(self, _: f64) -> Result<Option<bool>, E> {
                Ok(None)
            }
            fn visit_str<E>(self, _: &str) -> Result<Option<bool>, E> {
                Ok(None)
            }
            fn visit_unit<E>(self) -> Result<Option<bool>, E> {
                Ok(None)
            }
            fn visit_none<E>(self) -> Result<Option<bool>, E> {
                Ok(None)
            }
            fn visit_map<A: serde::de::MapAccess<'de>>(
                self,
                mut map: A,
            ) -> Result<Option<bool>, A::Error> {
                while map
                    .next_entry::<serde::de::IgnoredAny, serde::de::IgnoredAny>(
                    )?
                    .is_some()
                {}
                Ok(None)
            }
        }
        deserializer.deserialize_any(V)
    }
}

struct RowFactVisitor<'k> {
    kind: &'k str,
    want_title: bool,
}

impl<'de> serde::de::Visitor<'de> for RowFactVisitor<'_> {
    type Value = FastFact;
    fn expecting(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str("a JSON object")
    }
    fn visit_map<A: serde::de::MapAccess<'de>>(
        self,
        mut map: A,
    ) -> Result<FastFact, A::Error> {
        let mut used = false;
        let mut has_error = false;
        let mut has_visible_part = false;
        let mut content_seen: Option<bool> = None;
        let mut user_title: Option<String> = None;
        let mut need_fallback = false;
        while let Some(key) = map.next_key::<std::borrow::Cow<'de, str>>()? {
            match (self.kind, key.as_ref()) {
                (_, "cost") => used |= map.next_value_seed(PositiveSeed)?,
                (_, "tokens") => used |= map.next_value_seed(TokensSeed)?,
                (_, "error") => has_error = map.next_value_seed(NonNullSeed)?,
                ("user", "text") => {
                    if let Some(s) = map.next_value_seed(OptStrSeed)? {
                        if self.want_title {
                            user_title = crate::providers::sqlite::title(&s);
                            has_visible_part |=
                                user_title.is_some() || is_non_empty_clean(&s);
                        } else {
                            has_visible_part |= is_non_empty_clean(&s);
                        }
                    }
                }
                ("user", "files" | "agents" | "skills") => {
                    if map.next_value_seed(NonEmptyArraySeed)? {
                        need_fallback = true;
                    }
                }
                ("assistant", "content") => {
                    content_seen = map.next_value_seed(AssistantContentSeed)?;
                }
                _ => {
                    map.next_value::<serde::de::IgnoredAny>()?;
                }
            }
        }
        if need_fallback {
            return Ok(FastFact::Fallback);
        }
        match self.kind {
            "user" => {
                if used || has_visible_part || has_error {
                    Ok(FastFact::Count { title: user_title })
                } else {
                    Ok(FastFact::Skip)
                }
            }
            "assistant" => match content_seen {
                // Missing/non-array content is a corrupt message that still counts.
                None => Ok(FastFact::Count { title: None }),
                Some(visible) => {
                    if used || visible || has_error {
                        Ok(FastFact::Count { title: None })
                    } else {
                        Ok(FastFact::Skip)
                    }
                }
            },
            _ => Ok(FastFact::Count { title: None }),
        }
    }
}

fn fast_v2_fact(kind: &str, bytes: &[u8], want_title: bool) -> FastFact {
    if kind == "idle" {
        return FastFact::Skip;
    }
    let Ok(text_str) = std::str::from_utf8(bytes) else {
        return FastFact::Fallback;
    };
    let trimmed = text_str.trim_start_matches([' ', '\t', '\n', '\r']);
    if !trimmed.starts_with('{') {
        return FastFact::Fallback;
    }
    let mut de = serde_json::Deserializer::from_str(trimmed);
    match serde::Deserializer::deserialize_map(
        &mut de,
        RowFactVisitor { kind, want_title },
    ) {
        Ok(fact) if de.end().is_ok() => fact,
        _ => FastFact::Fallback,
    }
}

pub fn facts(
    connection: &Connection,
    sessions: &str,
    parameters: &[&dyn ToSql],
    needs_title: Option<&HashSet<String>>,
) -> crate::Result<HashMap<String, Facts>> {
    let mut facts: HashMap<String, (Facts, i64)> = HashMap::new();
    let sql = format!(
        "SELECT id, session_id, type, seq, time_created, data \
         FROM session_message WHERE session_id IN ({sessions})"
    );
    let mut statement = connection.prepare(&sql)?;
    let mut rows = statement.query(parameters)?;
    while let Some(r) = rows.next()? {
        let kind_ref = r.get_ref(2)?;
        let kind = match kind_ref {
            ValueRef::Text(b) => std::str::from_utf8(b).unwrap_or(""),
            _ => "",
        };
        if kind == "idle" {
            continue;
        }
        let session_id = match r.get_ref(1)? {
            ValueRef::Text(b) => std::str::from_utf8(b)?,
            other => {
                let s = string(&value_from_ref(other)?);
                let seq = match r.get_ref(3)? {
                    ValueRef::Integer(v) => v,
                    other => integer(&value_from_ref(other)?),
                };
                let (entry, first) = facts.entry(s).or_default();
                entry.count += 1;
                let _ = (seq, first);
                continue;
            }
        };
        let seq = match r.get_ref(3)? {
            ValueRef::Integer(v) => v,
            other => integer(&value_from_ref(other)?),
        };
        let want_title = kind == "user"
            && needs_title.is_none_or(|set| set.contains(session_id))
            && facts
                .get(session_id)
                .is_none_or(|(f, first)| f.title.is_none() || seq < *first);
        let fast = match r.get_ref(5)? {
            ValueRef::Text(bytes) => fast_v2_fact(kind, bytes, want_title),
            _ => FastFact::Fallback,
        };
        match fast {
            FastFact::Skip => {}
            FastFact::Count { title } => {
                let (entry, first) =
                    if let Some(pair) = facts.get_mut(session_id) {
                        pair
                    } else {
                        facts.entry(session_id.to_owned()).or_default()
                    };
                entry.count += 1;
                if let Some(title) = title
                    && (entry.title.is_none() || seq < *first)
                {
                    entry.title = Some(title);
                    *first = seq;
                }
            }
            FastFact::Fallback => {
                let id_val = value_from_ref(r.get_ref(0)?)?;
                let kind_val = value_from_ref(kind_ref)?;
                let seq_val = value_from_ref(r.get_ref(3)?)?;
                let time_val = value_from_ref(r.get_ref(4)?)?;
                let data = json_from_ref(r.get_ref(5)?);
                let msg = match data.and_then(|data| {
                    message_from_parts(
                        string(&id_val),
                        kind_val,
                        seq_val,
                        &time_val,
                        data,
                    )
                }) {
                    Ok(None) => continue,
                    Ok(Some(msg)) => Some(msg),
                    Err(_) => None,
                };
                let (entry, first) =
                    if let Some(pair) = facts.get_mut(session_id) {
                        pair
                    } else {
                        facts.entry(session_id.to_owned()).or_default()
                    };
                entry.count += 1;
                if (entry.title.is_none() || seq < *first)
                    && let Some(title) = msg.and_then(|msg| {
                        crate::providers::sqlite::user_title(
                            std::slice::from_ref(&msg),
                        )
                    })
                {
                    entry.title = Some(title);
                    *first = seq;
                }
            }
        }
    }
    Ok(facts
        .into_iter()
        .map(|(session, (facts, _))| (session, facts))
        .collect())
}

#[cfg(test)]
fn message(row: &Value) -> crate::Result<Option<Message>> {
    let data = crate::providers::sqlite::connection::json_cell(&row["data"])?;
    message_from_parts(
        string(&row["id"]),
        row["type"].clone(),
        row["seq"].clone(),
        &row["time_created"],
        data,
    )
}

fn message_from_parts(
    id: String,
    kind_val: Value,
    seq_val: Value,
    time_val: &Value,
    mut data: Value,
) -> crate::Result<Option<Message>> {
    let Some(mut obj) = data.as_object_mut().map(std::mem::take) else {
        return Err("message data must be an object".into());
    };
    let kind = text(&kind_val);
    if kind == "idle" {
        return Ok(None);
    }
    let role = match kind {
        "user" => "user",
        "assistant" => "assistant",
        "system" | "skill" => "system",
        "shell" => "tool",
        "compaction" => "compaction",
        "synthetic" | "agent-switched" | "model-switched"
        | "location-switched" => "custom",
        _ => "unknown",
    };
    let timestamp = integer(time_val);
    let mut message = Message::new(id, role, timestamp, Vec::new());
    message.agent = obj.get("agent").and_then(Value::as_str).map(str::to_owned);
    if let Some(model) = obj.get("model") {
        message.model = model["id"].as_str().map(std::convert::Into::into);
        message.provider = model["providerID"].as_str().map(str::to_owned);
    }
    if let Some(time) = obj.get("time")
        && !time["completed"].is_null()
    {
        message.time_completed = integer(&time["completed"]).into();
    }
    message.tokens = obj
        .get("tokens")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    message.cost =
        serde_json::Number::from_f64(obj.get("cost").map_or(0.0, float))
            .unwrap();
    let used = usage_map(&obj);
    let line = |text: String| Part::text(text, timestamp);
    let parts = &mut message.parts;
    match kind {
        "user" => {
            let t = match obj.remove("text").unwrap_or(Value::Null) {
                Value::String(s) => s,
                _ => String::new(),
            };
            parts.push(line(t));
            if let Some(Value::Array(files)) = obj.remove("files") {
                for file in &files {
                    let image = file["mime"]
                        .as_str()
                        .is_some_and(|mime| mime.starts_with("image/"))
                        && file["data"]
                            .as_str()
                            .is_some_and(|data| !data.is_empty());
                    parts.push(if image {
                        Part::Image(ImagePart {
                            mime_type: file["mime"].as_str().map(str::to_owned),
                            data: file["data"].clone(),
                            time_created: timestamp,
                        })
                    } else {
                        line(attachment(file))
                    });
                }
            }
            for mention in ["agents", "skills"].iter().flat_map(|name| {
                obj.get(*name)
                    .and_then(Value::as_array)
                    .into_iter()
                    .flatten()
            }) {
                if let Some(name) =
                    mention["name"].as_str().filter(|name| !name.is_empty())
                {
                    parts.push(line(format!("@{name}")));
                }
            }
        }
        "assistant" => {
            let data_content = obj.remove("content").unwrap_or(Value::Null);
            let content =
                data_content.as_array().ok_or("content must be an array")?;
            parts.extend(
                content.iter().map(|item| content_part(item, timestamp)),
            );
            let children: HashSet<_> = parts
                .iter()
                .filter_map(|part| match part {
                    Part::Tool(tool)
                        if matches!(
                            tool.tool.as_str(),
                            "task" | "subagent"
                        ) =>
                    {
                        tool.state.get("metadata")
                    }
                    _ => None,
                })
                .flat_map(|metadata| {
                    ["sessionId", "sessionID"].into_iter().filter_map(
                        move |key| {
                            metadata[key]
                                .as_str()
                                .filter(|id| !id.trim().is_empty())
                        },
                    )
                })
                .collect();
            let child = (children.len() == 1)
                .then(|| children.into_iter().next().map(str::to_owned))
                .flatten();
            message.subagent_id = child;
        }
        "shell" => parts.push(shell_map(&obj, timestamp)),
        "compaction" => {
            let status =
                obj.get("status").map_or_else(|| "undefined".into(), plain);
            let mut sections = vec![format!("[Compaction: {status}]")];
            for name in ["summary", "recent"] {
                if let Some(text) = obj
                    .get(name)
                    .and_then(Value::as_str)
                    .filter(|text| !text.is_empty())
                {
                    sections.push(text.into());
                }
            }
            parts.push(line(sections.join("\n\n")));
        }
        "synthetic" | "system" | "skill" => {
            let label = obj
                .get("description")
                .and_then(Value::as_str)
                .or_else(|| obj.get("name").and_then(Value::as_str))
                .unwrap_or_default();
            parts.push(line(format!("[{kind}] {label}")));
            let t = match obj.remove("text").unwrap_or(Value::Null) {
                Value::String(s) => s,
                _ => String::new(),
            };
            parts.push(line(t));
        }
        _ => {
            let rendered =
                serde_json::to_string_pretty(&obj).unwrap_or_default();
            parts.push(line(format!("[{kind}] {rendered}")));
        }
    }
    obj.remove("text");
    obj.remove("content");
    obj.remove("files");
    if let Some(error) = obj.get("error").filter(|v| !v.is_null()) {
        message
            .parts
            .push(line(format!("[Error] {}", describe(error))));
    }
    obj.insert("seq".into(), seq_val);
    message.entry_type = Some(kind_val);
    message.metadata = Some(obj);
    let mut messages = vec![message];
    crate::providers::text::clean_messages(&mut messages);
    Ok(messages
        .pop()
        .filter(|message| used || !message.parts.is_empty()))
}

fn content_part(content: &Value, timestamp: i64) -> Part {
    match content["type"].as_str() {
        Some("text") => Part::text(text(&content["text"]).into(), timestamp),
        Some("reasoning") => Part::Reasoning(TextPart {
            text: text(&content["text"]).into(),
            time_created: timestamp,
        }),
        Some("tool") if !text(&content["name"]).is_empty() => {
            tool(content, timestamp)
        }
        _ => Part::text(
            format!("[Unknown content] {}", describe(content)),
            timestamp,
        ),
    }
}

fn tool(content: &Value, timestamp: i64) -> Part {
    let mut state = object(&content["state"]);
    let invalid_error = (content["name"] == "invalid")
        .then(|| {
            state
                .get("input")
                .and_then(|input| input["error"].as_str())
                .filter(|error| !error.trim().is_empty())
                .map(str::to_owned)
        })
        .flatten();
    let status = match state.get("status").and_then(Value::as_str) {
        _ if invalid_error.is_some() => "error",
        Some("completed") => "completed",
        Some("error") => "error",
        _ => "running",
    };
    state.insert("status".into(), status.into());
    let mut output = match state.remove("content") {
        Some(Value::Array(items)) => items,
        _ => Vec::new(),
    };
    if let Some(error) = state
        .get("error")
        .and_then(|error| error["message"].as_str())
    {
        output.push(json!({"type": "text", "text": error}));
    }
    if let Some(error) = invalid_error {
        state.insert("error".into(), error.into());
    }
    if !output.is_empty() {
        state.insert("output".into(), output.into());
    }
    let time = object(&content["time"]);
    let created = time.get("created").map_or(timestamp, integer);
    state.insert("time".into(), time.into());
    for field in ["executed", "providerState", "providerResultState"] {
        if let Some(value) = content.get(field) {
            state.insert(field.into(), value.clone());
        }
    }
    let name = text(&content["name"]);
    Part::Tool(Box::new(ToolPart {
        subagent_type: None,
        tool: name.into(),
        call_id: text(&content["id"]).into(),
        title: name.into(),
        state,
        time_created: created,
        nickname: None,
        subagent_id: None,
    }))
}

fn shell_map(data: &Map<String, Value>, timestamp: i64) -> Part {
    let field = |name: &str| data.get(name).unwrap_or(&Value::Null);
    let status = match field("status").as_str() {
        Some("running") => "running",
        Some("exited")
            if field("exit").is_null() || float(field("exit")) == 0.0 =>
        {
            "completed"
        }
        _ => "error",
    };
    let output = field("output");
    let mut state = Map::from_iter([
        ("status".into(), status.into()),
        (
            "input".into(),
            data.get("command").map_or_else(
                || json!({}),
                |command| json!({"command": command}),
            ),
        ),
        ("output".into(), output["output"].clone()),
        ("exit".into(), field("exit").clone()),
        ("truncated".into(), output["truncated"].clone()),
        ("time".into(), object(field("time")).into()),
    ]);
    if status == "error" {
        let exit = if field("exit").is_null() {
            "unknown".into()
        } else {
            plain(field("exit"))
        };
        state.insert(
            "error".into(),
            format!("Shell {} (exit: {exit})", plain(field("status"))).into(),
        );
    }
    let command = text(field("command"));
    Part::Tool(Box::new(ToolPart {
        subagent_type: None,
        tool: "shell".into(),
        call_id: text(field("shellID")).into(),
        title: command.into(),
        state,
        time_created: timestamp,
        nickname: None,
        subagent_id: None,
    }))
}

fn attachment(file: &Value) -> String {
    let uri = if file["uri"].is_null() {
        &file["source"]["uri"]
    } else {
        &file["uri"]
    };
    let fields: Vec<_> = [&file["name"], &file["mime"], uri]
        .into_iter()
        .filter(|value| !matches!(value, Value::Null | Value::Bool(false)))
        .filter(|value| *value != "")
        .map(plain)
        .collect();
    format!("[Attachment] {}", fields.join(" · "))
}

fn usage_map(data: &Map<String, Value>) -> bool {
    let tokens = data.get("tokens").unwrap_or(&Value::Null);
    let positive = |value: &Value| value.as_f64().is_some_and(|n| n > 0.0);
    data.get("cost").is_some_and(positive)
        || [
            &tokens["input"],
            &tokens["output"],
            &tokens["reasoning"],
            &tokens["cache"]["read"],
            &tokens["cache"]["write"],
        ]
        .into_iter()
        .any(positive)
}

fn describe(value: &Value) -> String {
    value.as_str().map_or_else(
        || serde_json::to_string_pretty(value).unwrap_or_default(),
        str::to_owned,
    )
}

fn plain(value: &Value) -> String {
    match value {
        Value::Null => String::new(),
        Value::String(text) => text.clone(),
        value => value.to_string(),
    }
}

fn object(value: &Value) -> Map<String, Value> {
    value.as_object().cloned().unwrap_or_default()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn assistant_message(content: &[Value]) -> Message {
        let row = json!({
            "id": "assistant",
            "type": "assistant",
            "time_created": 1000,
            "data": json!({ "content": content }).to_string(),
        });
        message(&row).unwrap().unwrap()
    }

    #[test]
    fn links_only_unambiguous_task_and_subagent_children() {
        let call = |name: &str, metadata: Value| {
            json!({
                "type": "tool",
                "name": name,
                "state": { "status": "completed", "metadata": metadata },
            })
        };
        for (content, expected) in [
            (
                vec![call("task", json!({ "sessionId": "child" }))],
                Some("child"),
            ),
            (
                vec![call("task", json!({ "sessionID": "child" }))],
                Some("child"),
            ),
            (
                vec![call("subagent", json!({ "sessionId": "child" }))],
                Some("child"),
            ),
            (
                vec![call("subagent", json!({ "sessionID": "child" }))],
                Some("child"),
            ),
            (
                vec![
                    call("task", json!({ "sessionId": "child" })),
                    call("subagent", json!({ "sessionID": "child" })),
                ],
                Some("child"),
            ),
            (
                vec![
                    call("task", json!({ "sessionId": "child" })),
                    call("task", json!({ "sessionId": "other" })),
                ],
                None,
            ),
            (
                vec![call(
                    "task",
                    json!({ "sessionId": "child", "sessionID": "other" }),
                )],
                None,
            ),
            (vec![call("task", json!({ "sessionId": "   " }))], None),
            (vec![call("read", json!({ "sessionId": "child" }))], None),
        ] {
            let parsed = assistant_message(&content);
            assert_eq!(parsed.subagent_id.as_deref(), expected);
        }
    }

    #[test]
    fn invalid_input_error_marks_tool_failed_without_guessing_others() {
        let err = "Invalid input for tool edit: JSON parsing failed";
        let parsed = assistant_message(&[
            json!({
                "type": "tool",
                "id": "c1",
                "name": "invalid",
                "state": {
                    "status": "completed",
                    "input": { "tool": "edit", "error": err },
                    "content": [{ "type": "text", "text": "[Old tool result content cleared]" }],
                },
            }),
            json!({
                "type": "tool",
                "id": "c2",
                "name": "edit",
                "state": {
                    "status": "completed",
                    "input": { "error": err },
                    "content": [{ "type": "text", "text": "error mentioned in output" }],
                },
            }),
            json!({
                "type": "tool",
                "id": "c3",
                "name": "invalid",
                "state": {
                    "status": "completed",
                    "input": { "tool": "edit", "error": "  " },
                    "content": [],
                },
            }),
        ]);
        let Part::Tool(invalid) = &parsed.parts[0] else {
            panic!("expected tool");
        };
        assert_eq!(invalid.state["status"], "error");
        assert_eq!(invalid.state["error"], err);
        assert_eq!(
            invalid.state["output"],
            json!([{ "type": "text", "text": "[Old tool result content cleared]" }])
        );
        for part in &parsed.parts[1..] {
            let Part::Tool(tool) = part else {
                panic!("expected tool");
            };
            assert_eq!(tool.state["status"], "completed");
            assert!(!tool.state.contains_key("error"));
        }
    }

    #[test]
    fn decimal_cost_counts_in_v2_facts() {
        let conn = Connection::open_in_memory().unwrap();
        conn.execute_batch(
            "CREATE TABLE session_v2 (id TEXT);
             CREATE TABLE session_message (id TEXT, session_id TEXT, \
                 type TEXT, seq INTEGER, time_created INTEGER, data TEXT);
             INSERT INTO session_v2 VALUES ('s1');
             INSERT INTO session_message VALUES \
                 ('m1', 's1', 'assistant', 1, 1000, '{\"content\":[],\"cost\":0.25}');",
        )
        .unwrap();
        let result =
            facts(&conn, "SELECT id FROM session_v2", &[], None).unwrap();
        assert_eq!(result.get("s1").map(|f| f.count), Some(1));
    }
}
