use super::{Error, from_slice, from_str};
use serde_json::Value;

pub fn from_bytes(bytes: &[u8]) -> crate::Result<Value> {
    let (width, little, skip) = if bytes.starts_with(&[0xff, 0xfe, 0, 0]) {
        (4, true, 4)
    } else if bytes.starts_with(&[0, 0, 0xfe, 0xff]) {
        (4, false, 4)
    } else if bytes.starts_with(&[0xff, 0xfe]) {
        (2, true, 2)
    } else if bytes.starts_with(&[0xfe, 0xff]) {
        (2, false, 2)
    } else if bytes.starts_with(&[0xef, 0xbb, 0xbf]) {
        return from_slice(&bytes[3..]);
    } else if bytes.len() >= 4 && bytes[0] == 0 {
        (if bytes[1] == 0 { 4 } else { 2 }, false, 0)
    } else if bytes.len() >= 4 && bytes[1] == 0 {
        (if bytes[2] == 0 && bytes[3] == 0 { 4 } else { 2 }, true, 0)
    } else if bytes.len() == 2 && bytes.contains(&0) {
        (2, bytes[0] != 0, 0)
    } else {
        return from_slice(bytes);
    };
    let encoding = match (width, little) {
        (4, true) => "utf-32-le",
        (4, false) => "utf-32-be",
        (_, true) => "utf-16-le",
        (_, false) => "utf-16-be",
    };
    let mut text = String::new();
    let mut index = skip;
    while index < bytes.len() {
        if bytes.len() - index < width {
            return Err(decode_error(bytes, encoding, index, bytes.len(), "truncated data").into());
        }
        let mut code = match (width, little) {
            (4, true) => u32::from_le_bytes(bytes[index..index + 4].try_into().unwrap()),
            (4, false) => u32::from_be_bytes(bytes[index..index + 4].try_into().unwrap()),
            (_, true) => u16::from_le_bytes(bytes[index..index + 2].try_into().unwrap()).into(),
            (_, false) => u16::from_be_bytes(bytes[index..index + 2].try_into().unwrap()).into(),
        };
        let start = index;
        index += width;
        if width == 2 && (0xd800..=0xdbff).contains(&code) && bytes.len() - index >= 2 {
            let next = if little {
                u16::from_le_bytes(bytes[index..index + 2].try_into().unwrap())
            } else {
                u16::from_be_bytes(bytes[index..index + 2].try_into().unwrap())
            };
            if (0xdc00..=0xdfff).contains(&next) {
                code = 0x10000 + ((code - 0xd800) << 10) + u32::from(next - 0xdc00);
                index += 2;
            }
        }
        let character = char::from_u32(code).ok_or_else(|| {
            decode_error(
                bytes,
                encoding,
                start,
                index,
                "code point not in range(0x110000)",
            )
        })?;
        text.push(character);
    }
    from_str(&text)
}

fn decode_error(bytes: &[u8], encoding: &str, start: usize, end: usize, reason: &str) -> Error {
    let evidence = if end == start + 1 {
        format!("byte 0x{:02x} in position {start}", bytes[start])
    } else {
        format!("bytes in position {start}-{}", end - 1)
    };
    Error {
        kind: "UnicodeDecodeError",
        message: format!("'{encoding}' codec can't decode {evidence}: {reason}"),
    }
}
