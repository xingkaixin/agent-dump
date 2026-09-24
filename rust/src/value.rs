use serde_json::Value;

pub fn type_name(value: &Value) -> &'static str {
    match value {
        Value::Null => "NoneType",
        Value::Bool(_) => "bool",
        Value::Number(number) if number.as_str().contains(['.', 'e', 'E']) => "float",
        Value::Number(_) => "int",
        Value::String(_) => "str",
        Value::Array(_) => "list",
        Value::Object(_) => "dict",
    }
}

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
    crate::python_json::from_str(raw.as_str()?)
        .ok()
        .filter(Value::is_object)
}

pub fn parse_json(raw: &Value) -> Value {
    raw.as_str()
        .and_then(|text| crate::python_json::from_str(text).ok())
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
    if let Some(value) = crate::python_json::nonfinite(number) {
        return if value.is_nan() {
            "nan"
        } else if value.is_sign_negative() {
            "-inf"
        } else {
            "inf"
        }
        .into();
    }
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
                out.push_str(&if crate::python_json::nonfinite(number).is_some() {
                    crate::python_json::number_text(number)
                } else {
                    number_text(number)
                });
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

pub fn repr(value: &Value) -> String {
    match value {
        Value::String(text) => quoted(text),
        _ => string(value),
    }
}

fn quoted(text: &str) -> String {
    static NONPRINTABLE: std::sync::LazyLock<regex::Regex> =
        std::sync::LazyLock::new(|| regex::Regex::new(r"[\p{Other}\p{Separator}]").unwrap());
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
            c if c != ' ' && NONPRINTABLE.is_match(c.encode_utf8(&mut [0; 4])) => {
                let code = u32::from(c);
                result.push_str(&if code <= 255 {
                    format!("\\x{code:02x}")
                } else if code <= 65535 {
                    format!("\\u{code:04x}")
                } else {
                    format!("\\U{code:08x}")
                });
            }
            c => result.push(c),
        }
    }
    result.push(quote);
    result
}

pub fn parsed_string(value: &Value) -> Option<Value> {
    let parsed: Value = crate::python_json::from_str(value.as_str()?.trim()).ok()?;
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

pub fn integer_number(value: &Value) -> serde_json::Number {
    let text = match value {
        Value::Number(number) => {
            let raw = number.to_string();
            if !raw.contains(['.', 'e', 'E']) {
                return number.clone();
            }
            let Some(number) = number.as_f64() else {
                return 0.into();
            };
            format!("{:.0}", number.trunc())
        }
        Value::String(text) => text.trim().chars().map(decimal_digit).collect(),
        _ => return 0.into(),
    };
    use std::sync::LazyLock;
    static INTEGER: LazyLock<regex::Regex> =
        LazyLock::new(|| regex::Regex::new(r"^[+-]?[0-9]+(?:_[0-9]+)*$").unwrap());
    if !INTEGER.is_match(&text) {
        return 0.into();
    }
    text.replace('_', "")
        .parse::<num_bigint::BigInt>()
        .ok()
        .and_then(|number| number.to_string().parse().ok())
        .unwrap_or_else(|| 0.into())
}

pub fn add_integer(total: &mut serde_json::Number, value: &Value) {
    let value = integer_number(value);
    if let Some(sum) = total
        .as_i64()
        .zip(value.as_i64())
        .and_then(|(left, right)| left.checked_add(right))
    {
        *total = sum.into();
        return;
    }
    let left: num_bigint::BigInt = total.to_string().parse().unwrap();
    let right: num_bigint::BigInt = value.to_string().parse().unwrap();
    *total = (left + right).to_string().parse().unwrap();
}

fn decimal_digit(character: char) -> char {
    static DECIMAL: std::sync::LazyLock<regex::Regex> =
        std::sync::LazyLock::new(|| regex::Regex::new(r"^\p{Nd}$").unwrap());
    let is_decimal = |character: char| DECIMAL.is_match(character.encode_utf8(&mut [0; 4]));
    if character.is_ascii() || !is_decimal(character) {
        return character;
    }
    let code = u32::from(character);
    let mut start = code;
    // Unicode decimal digit blocks contain consecutive groups ordered zero to nine.
    while char::from_u32(start - 1).is_some_and(is_decimal) {
        start -= 1;
    }
    char::from_digit((code - start) % 10, 10).unwrap()
}
