use serde_json::Value;

pub fn text(value: &Value) -> &str {
    value.as_str().unwrap_or("")
}

pub fn integer(value: &Value) -> i64 {
    integer_or(value, 0)
}

pub fn integer_or(value: &Value, default: i64) -> i64 {
    value
        .as_i64()
        .or_else(|| value.as_str().and_then(|value| value.trim().parse().ok()))
        .or_else(|| value.as_f64().map(|value| value as i64))
        .unwrap_or(default)
}

pub fn float(value: &Value) -> f64 {
    value
        .as_f64()
        .or_else(|| {
            value
                .as_str()
                .and_then(|text| text.trim().parse::<f64>().ok())
        })
        .filter(|number| number.is_finite())
        .unwrap_or(0.0)
}

pub fn json_object(raw: &Value) -> Option<Value> {
    serde_json::from_str::<Value>(raw.as_str()?)
        .ok()
        .filter(Value::is_object)
}

pub fn parse_json(raw: &Value) -> Value {
    raw.as_str()
        .and_then(|text| serde_json::from_str(text).ok())
        .unwrap_or_else(|| raw.clone())
}

pub fn objects(value: &Value) -> crate::Result<&[Value]> {
    value
        .as_array()
        .filter(|items| items.iter().all(Value::is_object))
        .map(Vec::as_slice)
        .ok_or_else(|| "Expected an array of objects".into())
}

pub fn field(value: &Value, key: &str) -> String {
    value.get(key).map(string).unwrap_or_default()
}

pub fn string(value: &Value) -> String {
    match value {
        Value::String(text) => text.clone(),
        Value::Null => "None".into(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        Value::Number(number) => number_text(number),
        Value::Array(values) => format!(
            "[{}]",
            values.iter().map(repr).collect::<Vec<_>>().join(", ")
        ),
        Value::Object(values) => format!(
            "{{{}}}",
            values
                .iter()
                .map(|(key, value)| format!("{}: {}", quoted(key), repr(value)))
                .collect::<Vec<_>>()
                .join(", ")
        ),
    }
}

fn number_text(number: &serde_json::Number) -> String {
    if !number.is_f64() {
        return number.to_string();
    }
    let text = format!("{:?}", number.as_f64().unwrap());
    match text.split_once('e') {
        Some((mantissa, exponent)) => {
            let exponent: i32 = exponent.parse().unwrap();
            format!("{mantissa}e{exponent:+03}")
        }
        None => text,
    }
}

pub fn pretty_json(value: &Value) -> String {
    fn append(value: &Value, depth: usize, out: &mut String) {
        let object = value.is_object();
        let items: Vec<_> = match value {
            Value::Object(values) => values
                .iter()
                .map(|(key, value)| (Some(key), value))
                .collect(),
            Value::Array(values) => values.iter().map(|value| (None, value)).collect(),
            Value::Number(number) => {
                out.push_str(&number_text(number));
                return;
            }
            _ => {
                out.push_str(&serde_json::to_string(value).unwrap());
                return;
            }
        };
        out.push(if object { '{' } else { '[' });
        for (index, (key, value)) in items.iter().enumerate() {
            out.push_str(if index == 0 { "\n" } else { ",\n" });
            out.push_str(&"  ".repeat(depth + 1));
            if let Some(key) = key {
                out.push_str(&serde_json::to_string(key).unwrap());
                out.push_str(": ");
            }
            append(value, depth + 1, out);
        }
        if !items.is_empty() {
            out.push('\n');
            out.push_str(&"  ".repeat(depth));
        }
        out.push(if object { '}' } else { ']' });
    }
    let mut output = String::new();
    append(value, 0, &mut output);
    output
}

fn repr(value: &Value) -> String {
    match value {
        Value::String(text) => quoted(text),
        _ => string(value),
    }
}

fn quoted(text: &str) -> String {
    let quote = if text.contains('\'') && !text.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut result = quote.to_string();
    for c in text.chars() {
        match c {
            '\\' => result.push_str("\\\\"),
            '\n' => result.push_str("\\n"),
            '\r' => result.push_str("\\r"),
            '\t' => result.push_str("\\t"),
            c if c == quote => {
                result.push('\\');
                result.push(c);
            }
            c if c.is_control() && u32::from(c) <= 255 => {
                result.push_str(&format!("\\x{:02x}", u32::from(c)))
            }
            c => result.push(c),
        }
    }
    result.push(quote);
    result
}

pub fn parsed_string(value: &Value) -> Option<Value> {
    let parsed: Value = serde_json::from_str(value.as_str()?.trim()).ok()?;
    (!parsed.is_null()).then_some(parsed)
}

pub fn truthy(value: &Value) -> bool {
    match value {
        Value::Null => false,
        Value::Bool(value) => *value,
        Value::Number(value) => value.as_f64() != Some(0.0),
        Value::String(value) => !value.is_empty(),
        Value::Array(value) => !value.is_empty(),
        Value::Object(value) => !value.is_empty(),
    }
}
