use crate::session::{ImagePart, Part};
use regex::Regex;
use serde_json::{Map, Number, Value};
use std::collections::HashMap;
use std::sync::LazyLock;

const MAX_SAFE_INTEGER: f64 = 9_007_199_254_740_991.0;

pub struct Call {
    pub name: String,
    pub args: Value,
}

/// Splits `mcp__server__tool` into the tool and its namespace.
pub fn split_tool_name(name: &str) -> (&str, &str) {
    if name.starts_with("mcp__")
        && let Some(separator) = name.rfind("__")
        && separator > 0
        && separator + 2 < name.len()
    {
        return (&name[separator + 2..], &name[..separator + 2]);
    }
    (name, "")
}

/// The output belongs to the last call that is not bookkeeping.
pub fn output_target(calls: &[Call]) -> Option<usize> {
    calls
        .iter()
        .rposition(|call| {
            !matches!(
                split_tool_name(&call.name).0,
                "apply_patch" | "update_plan"
            )
        })
        .or_else(|| calls.len().checked_sub(1))
}

pub fn patch_text(args: &Value) -> &str {
    args.as_str()
        .or_else(|| args.get("patch").and_then(Value::as_str))
        .unwrap_or("")
}

fn item_text(item: &Value) -> Option<&str> {
    item.as_str().or_else(|| item["text"].as_str())
}

/// Tool output blocks and the status they report.
pub fn output(value: &Value, time: i64) -> (Vec<Part>, &'static str) {
    static ENVELOPE: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(
            r"\AScript (?:completed|failed)\nWall time [^\n]*\nOutput:\n?",
        )
        .unwrap()
    });
    let items = match value {
        Value::Array(items) => items.as_slice(),
        Value::Null => &[],
        _ => std::slice::from_ref(value),
    };
    let first = items.iter().find_map(item_text).unwrap_or("");
    let status = if first.starts_with("Script failed\n") {
        "error"
    } else if first.starts_with("Script running with cell ID ") {
        "running"
    } else {
        "completed"
    };
    let text: String = items.iter().filter_map(item_text).collect();
    let text = ENVELOPE.replace(&text, "");
    let mut parts = Vec::new();
    if !text.trim().is_empty() {
        parts.push(Part::text(text.into_owned(), time));
    }
    for item in items {
        if item.is_null() || item_text(item).is_some() {
            continue;
        }
        if item["type"] == "input_image"
            && let Some(url) = item["image_url"].as_str()
        {
            let (mime_type, data) = url
                .strip_prefix("data:")
                .and_then(|url| url.split_once(";base64,"))
                .map_or((None, url), |(mime, data)| (Some(mime.into()), data));
            parts.push(Part::Image(ImagePart {
                mime_type,
                data: data.into(),
                time_created: time,
            }));
            continue;
        }
        let text = match item {
            Value::Object(_) | Value::Array(_) => {
                crate::compat::value::pretty_json(item)
            }
            _ => crate::compat::value::string(item),
        };
        parts.push(Part::text(text, time));
    }
    (parts, status)
}

/// Reads literal `tools.*` calls from exec code without running it.
pub fn decode(input: &Value) -> Vec<Call> {
    static ASSIGN: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"(?:const|let|var)\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*")
            .unwrap()
    });
    static CALL: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"tools\.([A-Za-z_$][A-Za-z0-9_$]*)\s*\(").unwrap()
    });
    let Some(input) = input.as_str().filter(|input| input.contains("tools."))
    else {
        return Vec::new();
    };
    let mut scope = HashMap::new();
    let mut pos = 0;
    while let Some(capture) = ASSIGN.captures_at(input, pos) {
        pos = capture.get(0).unwrap().end();
        let mut reader = Reader::new(input, pos, &scope);
        let value = reader.value(0);
        let end = reader.pos;
        if let Some(value) = value {
            pos = end;
            if let Literal::Value(Value::String(value)) = value {
                scope.insert(capture[1].to_owned(), value);
            }
        }
    }
    let mut calls = Vec::new();
    pos = 0;
    while let Some(capture) = CALL.captures_at(input, pos) {
        pos = capture.get(0).unwrap().end();
        let mut reader = Reader::new(input, pos, &scope);
        if let Some(args) = reader.value(0) {
            calls.push(Call {
                name: capture[1].to_owned(),
                args: match args {
                    Literal::Value(value) => value,
                    Literal::Undefined => Value::Null,
                },
            });
            pos = reader.pos;
        }
    }
    calls
}

enum Literal {
    Undefined,
    Value(Value),
}

struct Reader<'a> {
    src: &'a str,
    pos: usize,
    scope: &'a HashMap<String, String>,
}

impl<'a> Reader<'a> {
    const fn new(
        src: &'a str,
        pos: usize,
        scope: &'a HashMap<String, String>,
    ) -> Self {
        Self { src, pos, scope }
    }

    fn peek(&self) -> Option<u8> {
        self.src.as_bytes().get(self.pos).copied()
    }

    fn variable(&self, name: &str) -> Literal {
        self.scope
            .get(name)
            .cloned()
            .map_or(Literal::Undefined, |value| {
                Literal::Value(Value::String(value))
            })
    }

    fn value(&mut self, depth: usize) -> Option<Literal> {
        if depth > 256 {
            return None;
        }
        self.trivia();
        Some(match self.peek()? {
            b'{' => Literal::Value(self.object(depth + 1)?),
            b'[' => Literal::Value(self.array(depth + 1)?),
            quote @ (b'"' | b'\'' | b'`') => {
                Literal::Value(Value::String(self.string(quote)))
            }
            b'-' | b'+' | b'0'..=b'9' => Literal::Value(self.number()?),
            b'A'..=b'Z' | b'a'..=b'z' | b'_' | b'$' => {
                match self.identifier() {
                    "true" => Literal::Value(Value::Bool(true)),
                    "false" => Literal::Value(Value::Bool(false)),
                    "null" => Literal::Value(Value::Null),
                    "undefined" => Literal::Undefined,
                    name => self.variable(name),
                }
            }
            _ => return None,
        })
    }

    /// Consumes a separator and reports whether the container closed.
    fn separator(&mut self, close: u8) -> Option<bool> {
        self.trivia();
        match self.peek()? {
            b',' => {
                self.pos += 1;
                self.trivia();
                if self.peek() != Some(close) {
                    return Some(false);
                }
            }
            byte if byte == close => {}
            _ => return None,
        }
        self.pos += 1;
        Some(true)
    }

    fn object(&mut self, depth: usize) -> Option<Value> {
        self.pos += 1;
        let mut result = Map::new();
        self.trivia();
        if self.peek() == Some(b'}') {
            self.pos += 1;
            return Some(Value::Object(result));
        }
        loop {
            self.trivia();
            let key = match self.peek()? {
                quote @ (b'"' | b'\'' | b'`') => self.string(quote),
                b'A'..=b'Z' | b'a'..=b'z' | b'_' | b'$' => {
                    self.identifier().to_owned()
                }
                _ => return None,
            };
            self.trivia();
            let value = if self.peek() == Some(b':') {
                self.pos += 1;
                self.value(depth)?
            } else {
                self.variable(&key)
            };
            match value {
                Literal::Value(value) => {
                    result.insert(key, value);
                }
                Literal::Undefined => {
                    result.remove(&key);
                }
            }
            if self.separator(b'}')? {
                return Some(Value::Object(result));
            }
        }
    }

    fn array(&mut self, depth: usize) -> Option<Value> {
        self.pos += 1;
        let mut result = Vec::new();
        self.trivia();
        if self.peek() == Some(b']') {
            self.pos += 1;
            return Some(Value::Array(result));
        }
        loop {
            result.push(match self.value(depth)? {
                Literal::Value(value) => value,
                Literal::Undefined => Value::Null,
            });
            if self.separator(b']')? {
                return Some(Value::Array(result));
            }
        }
    }

    fn string(&mut self, quote: u8) -> String {
        self.pos += 1;
        let mut result = Vec::<u16>::new();
        while let Some(byte) = self.peek() {
            if byte == quote {
                self.pos += 1;
                break;
            }
            if byte == b'\\' {
                self.pos += 1;
                let Some(escaped) = self.peek() else { break };
                let replacement = match escaped {
                    b'n' => Some(10),
                    b't' => Some(9),
                    b'r' => Some(13),
                    b'b' => Some(8),
                    b'f' => Some(12),
                    b'v' => Some(11),
                    b'0' => Some(0),
                    _ => None,
                };
                if let Some(replacement) = replacement {
                    self.pos += 1;
                    result.push(replacement);
                    continue;
                }
                if matches!(escaped, b'u' | b'x') {
                    self.pos += 1;
                    let length = if escaped == b'u' { 4 } else { 2 };
                    let code = self
                        .src
                        .get(self.pos..self.pos + length)
                        .filter(|hex| {
                            hex.bytes().all(|b| b.is_ascii_hexdigit())
                        })
                        .and_then(|hex| u16::from_str_radix(hex, 16).ok());
                    if let Some(code) = code {
                        result.push(code);
                        self.pos += length;
                    } else {
                        result.push(u16::from(escaped));
                    }
                    continue;
                }
            }
            let character = self.src[self.pos..].chars().next().unwrap();
            self.pos += character.len_utf8();
            result.extend_from_slice(character.encode_utf16(&mut [0; 2]));
        }
        String::from_utf16_lossy(&result)
    }

    #[allow(
        clippy::cast_possible_truncation,
        reason = "Integral values are range checked against JavaScript's safe integers"
    )]
    fn number(&mut self) -> Option<Value> {
        static NUMBER: LazyLock<Regex> = LazyLock::new(|| {
            Regex::new(
                r"\A[-+]?(?:0[xX][0-9a-fA-F]+|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?)",
            )
            .unwrap()
        });
        let token = NUMBER.find(&self.src[self.pos..])?.as_str();
        self.pos += token.len();
        let number = if let Some(hex) = token
            .strip_prefix("0x")
            .or_else(|| token.strip_prefix("0X"))
        {
            hex.chars().fold(0.0_f64, |value, digit| {
                value.mul_add(16.0, f64::from(digit.to_digit(16).unwrap()))
            })
        } else {
            token.parse::<f64>().unwrap_or(f64::NAN)
        };
        Some(
            if number.fract() == 0.0 && number.abs() <= MAX_SAFE_INTEGER {
                Value::Number(Number::from(number as i64))
            } else {
                Number::from_f64(number).map_or(Value::Null, Value::Number)
            },
        )
    }

    fn identifier(&mut self) -> &'a str {
        let start = self.pos;
        while self.peek().is_some_and(|byte| {
            byte.is_ascii_alphanumeric() || byte == b'_' || byte == b'$'
        }) {
            self.pos += 1;
        }
        &self.src[start..self.pos]
    }

    fn trivia(&mut self) {
        loop {
            let rest = &self.src[self.pos..];
            match self.peek() {
                Some(b' ' | b'\t' | b'\n' | b'\r') => self.pos += 1,
                Some(b'/') if rest.starts_with("//") => {
                    self.pos = rest[2..]
                        .find('\n')
                        .map_or(self.src.len(), |offset| self.pos + 3 + offset);
                }
                Some(b'/') if rest.starts_with("/*") => {
                    self.pos = rest[2..]
                        .find("*/")
                        .map_or(self.src.len(), |offset| self.pos + 4 + offset);
                }
                _ => return,
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn decodes_literal_tool_calls_without_running_code() {
        let calls = decode(&json!(
            r#"const patch = "a: \"x\"\npath\\to";
            await tools.exec_command({cmd:'ls', workdir:`/tmp/p`, yield_time_ms:10000});
            await tools.apply_patch({patch});
            tools.bad({x: fn()});
            tools.update_plan({plan:[{step:"a",status:"done"},], drop:undefined,
            /* skip */ n:[0x20, -0x20, 1.5e2], text:'😀\x41'});
            // comment
            tools.mcp__node_repl__js({code:"1"});"#
        ));
        let names: Vec<_> = calls.iter().map(|call| &call.name[..]).collect();
        assert_eq!(
            names,
            [
                "exec_command",
                "apply_patch",
                "update_plan",
                "mcp__node_repl__js"
            ]
        );
        assert_eq!(
            calls[0].args,
            json!({"cmd":"ls","workdir":"/tmp/p","yield_time_ms":10000})
        );
        assert_eq!(patch_text(&calls[1].args), "a: \"x\"\npath\\to");
        assert_eq!(
            calls[2].args,
            json!({"plan":[{"step":"a","status":"done"}],"n":[32,null,150],"text":"😀A"})
        );
        assert_eq!(output_target(&calls), Some(3));
        assert_eq!(output_target(&calls[1..3]), Some(1));
        assert_eq!(split_tool_name(&calls[3].name), ("js", "mcp__node_repl__"));
        assert!(decode(&json!("console.log(1)")).is_empty());
    }

    #[test]
    fn output_strips_the_script_envelope_and_keeps_images() {
        let (parts, status) = output(
            &json!([
                {"type":"input_text","text":"Script failed\nWall time 1s\nOutput:\nboom"},
                {"type":"input_image","image_url":"data:image/png;base64,AAAA"},
                {"type":"input_image","image_url":"https://example.test/a.png"}
            ]),
            7,
        );
        assert_eq!(status, "error");
        assert_eq!(
            serde_json::to_value(parts).unwrap(),
            json!([
                {"type":"text","text":"boom","time_created":7},
                {"type":"image","mime_type":"image/png","data":"AAAA","time_created":7},
                {
                    "type":"image",
                    "mime_type":null,
                    "data":"https://example.test/a.png",
                    "time_created":7
                }
            ])
        );
        assert_eq!(
            output(&json!("Script running with cell ID 1"), 0).1,
            "running"
        );
    }
}
