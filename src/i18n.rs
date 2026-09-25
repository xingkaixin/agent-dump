use std::collections::HashMap;
use std::sync::OnceLock;

pub fn terminal(key: &str, zh: bool, values: &[(&str, String)]) -> String {
    t(
        key,
        zh,
        &values
            .iter()
            .map(|(key, value)| (*key, crate::render::safe_line(value)))
            .collect::<Vec<_>>(),
    )
}

pub fn t(key: &str, zh: bool, values: &[(&str, String)]) -> String {
    static EN: OnceLock<HashMap<String, String>> = OnceLock::new();
    static ZH: OnceLock<HashMap<String, String>> = OnceLock::new();
    let catalog = if zh {
        ZH.get_or_init(|| {
            serde_json::from_str(include_str!("../resources/locales/zh.json")).unwrap()
        })
    } else {
        EN.get_or_init(|| {
            serde_json::from_str(include_str!("../resources/locales/en.json")).unwrap()
        })
    };
    let template = &catalog[key];
    let mut output = String::new();
    let mut rest = template.as_str();
    while let Some(start) = rest.find('{') {
        output.push_str(&rest[..start]);
        let Some(end) = rest[start..].find('}').map(|end| start + end) else {
            output.push_str(&rest[start..]);
            return output;
        };
        let field = &rest[start + 1..end];
        if let Some((_, value)) = values.iter().find(|(key, _)| *key == field) {
            output.push_str(value);
        } else {
            output.push_str(&rest[start..=end]);
        }
        rest = &rest[end + 1..];
    }
    output.push_str(rest);
    output
}
