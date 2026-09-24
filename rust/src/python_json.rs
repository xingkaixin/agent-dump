use serde_json::{Number, Value};
use std::io::{self, Write};

// serde_json has no non-finite variant. Normalize input overflows before using
// these valid number encodings internally; JSON output restores Python spellings.
const NAN: &str = "1e+9999";
const INFINITY: &str = "1e+999";
const NEG_INFINITY: &str = "-1e+999";

pub fn float(number: f64) -> Number {
    Number::from_f64(number).unwrap_or_else(|| {
        let text = if number.is_nan() {
            NAN
        } else if number.is_sign_negative() {
            NEG_INFINITY
        } else {
            INFINITY
        };
        text.parse().unwrap()
    })
}

pub fn nonfinite(number: &Number) -> Option<f64> {
    match number.as_str() {
        NAN => Some(f64::NAN),
        INFINITY => Some(f64::INFINITY),
        NEG_INFINITY => Some(f64::NEG_INFINITY),
        _ => None,
    }
}

fn normalize(value: &mut Value) {
    match value {
        Value::Number(number) if number.as_str().contains(['.', 'e', 'E']) => {
            if let Ok(value) = number.as_str().parse::<f64>()
                && !value.is_finite()
            {
                *number = float(value);
            }
        }
        Value::Array(items) => items.iter_mut().for_each(normalize),
        Value::Object(items) => items.values_mut().for_each(normalize),
        _ => {}
    }
}

pub fn from_slice(bytes: &[u8]) -> serde_json::Result<Value> {
    let original = serde_json::from_slice::<Value>(bytes);
    if let Ok(mut value) = original {
        normalize(&mut value);
        return Ok(value);
    }
    let mut encoded = Vec::with_capacity(bytes.len());
    let mut index = 0;
    let mut changed = false;
    while index < bytes.len() {
        let start = index;
        if bytes[index] == b'"' {
            index += 1;
            while index < bytes.len() {
                let byte = bytes[index];
                index += 1;
                if byte == b'\\' {
                    index = (index + 1).min(bytes.len());
                } else if byte == b'"' {
                    break;
                }
            }
            encoded.extend_from_slice(&bytes[start..index]);
        } else if b"{}[],: \r\n\t".contains(&bytes[index]) {
            encoded.push(bytes[index]);
            index += 1;
        } else {
            while index < bytes.len() && !b"{}[],: \r\n\t\"".contains(&bytes[index]) {
                index += 1;
            }
            let token = &bytes[start..index];
            let replacement = match token {
                b"NaN" => Some(NAN),
                b"Infinity" => Some(INFINITY),
                b"-Infinity" => Some(NEG_INFINITY),
                _ => None,
            };
            if let Some(replacement) = replacement {
                changed = true;
                encoded.extend_from_slice(replacement.as_bytes());
            } else if let Ok(mut value) = serde_json::from_slice::<Value>(token) {
                normalize(&mut value);
                if let Value::Number(number) = value {
                    encoded.extend_from_slice(number.as_str().as_bytes());
                } else {
                    encoded.extend_from_slice(token);
                }
            } else {
                encoded.extend_from_slice(token);
            }
        }
    }
    if changed {
        serde_json::from_slice(&encoded)
    } else {
        original
    }
}

pub fn from_str(text: &str) -> serde_json::Result<Value> {
    from_slice(text.as_bytes())
}

pub fn number_text(number: &Number) -> String {
    match nonfinite(number) {
        Some(value) if value.is_nan() => "NaN".into(),
        Some(value) if value.is_sign_negative() => "-Infinity".into(),
        Some(_) => "Infinity".into(),
        None => number.to_string(),
    }
}

#[derive(Default)]
pub struct Formatter(serde_json::ser::PrettyFormatter<'static>);

macro_rules! delegate {
    ($($name:ident($($argument:ident: $type:ty),*));* $(;)?) => {
        $(fn $name<W: ?Sized + Write>(&mut self, writer: &mut W, $($argument: $type),*) -> io::Result<()> {
            self.0.$name(writer, $($argument),*)
        })*
    };
}

impl serde_json::ser::Formatter for Formatter {
    delegate! {
        begin_array(); end_array(); begin_array_value(first: bool); end_array_value();
        begin_object(); end_object(); begin_object_key(first: bool);
        begin_object_value(); end_object_value();
    }
    fn write_number_str<W: ?Sized + Write>(
        &mut self,
        writer: &mut W,
        value: &str,
    ) -> io::Result<()> {
        let output = match value {
            NAN => "NaN",
            INFINITY => "Infinity",
            NEG_INFINITY => "-Infinity",
            _ => value,
        };
        writer.write_all(output.as_bytes())
    }
}
