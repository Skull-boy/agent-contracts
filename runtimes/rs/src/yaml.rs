//! YAML loading into the runtime's JSON value model.
//!
//! Contracts are YAML files whose data model is JSON: mappings with string
//! keys, sequences, strings, numbers, booleans, and null. `yaml-rust2` is the
//! single direct dependency (with `default-features = false`, so the UTF-16
//! decoder is not compiled in); this module converts its tree into [`Json`] and
//! fails closed on anything the JSON data model cannot represent.
//!
//! Deliberate limits, stated rather than discovered later:
//!
//! - Mapping keys must be strings. A YAML integer key (`1: value`) is rejected
//!   instead of being coerced, because the contract model is a JSON object.
//! - Anchors are resolved by the loader; an unresolved alias is an error.
//! - YAML 1.2 core-schema booleans only (`true`/`false`). PyYAML's YAML 1.1
//!   also accepts `yes`/`on`; a contract using those is rejected here, which is
//!   fail-closed rather than silently different.
//! - Duplicate keys take the last value, matching Python's `yaml.safe_load`
//!   (the reference behavior) rather than erroring.

use std::collections::BTreeMap;

use yaml_rust2::yaml::Hash;
use yaml_rust2::{Yaml, YamlLoader};

use crate::json::{Json, Number};

/// Parse a single YAML document into [`Json`].
pub fn parse(text: &str) -> Result<Json, String> {
    let documents = YamlLoader::load_from_str(text).map_err(|error| error.to_string())?;
    match documents.len() {
        0 => Ok(Json::Null),
        1 => convert(&documents[0]),
        count => Err(format!("expected a single YAML document, found {count}")),
    }
}

fn convert(value: &Yaml) -> Result<Json, String> {
    match value {
        Yaml::Null => Ok(Json::Null),
        Yaml::Boolean(flag) => Ok(Json::Bool(*flag)),
        Yaml::Integer(number) => Ok(Json::Number(Number::new(number.to_string()))),
        Yaml::Real(text) => Ok(Json::Number(Number::new(text.clone()))),
        Yaml::String(text) => Ok(Json::String(text.clone())),
        Yaml::Array(items) => {
            let mut converted = Vec::with_capacity(items.len());
            for item in items {
                converted.push(convert(item)?);
            }
            Ok(Json::Array(converted))
        }
        Yaml::Hash(entries) => convert_hash(entries),
        Yaml::Alias(_) => Err("unresolved YAML alias".to_string()),
        Yaml::BadValue => Err("invalid YAML value".to_string()),
    }
}

fn convert_hash(entries: &Hash) -> Result<Json, String> {
    let mut map: BTreeMap<String, Json> = BTreeMap::new();
    for (key, value) in entries {
        let name = match key {
            Yaml::String(text) => text.clone(),
            other => {
                return Err(format!(
                    "mapping keys must be strings, found {}",
                    yaml_kind(other)
                ))
            }
        };
        map.insert(name, convert(value)?);
    }
    Ok(Json::Object(map))
}

fn yaml_kind(value: &Yaml) -> &'static str {
    match value {
        Yaml::Null => "null",
        Yaml::Boolean(_) => "boolean",
        Yaml::Integer(_) | Yaml::Real(_) => "number",
        Yaml::String(_) => "string",
        Yaml::Array(_) => "array",
        Yaml::Hash(_) => "mapping",
        Yaml::Alias(_) => "alias",
        Yaml::BadValue => "invalid",
    }
}

/// Serialize [`Json`] as deterministic block YAML.
///
/// This is used only by the vector runner, which writes each vector's inline
/// contract to a scratch file and loads it back through the same loader. The
/// output is conservative (every string double-quoted, two-space indentation,
/// sorted keys) so the round trip is exact for any JSON-shaped value.
pub fn to_yaml(value: &Json) -> String {
    let mut out = String::new();
    emit_block(&mut out, value, 0);
    out
}

fn emit_block(out: &mut String, value: &Json, level: usize) {
    match value {
        Json::Object(map) if !map.is_empty() => {
            for (key, item) in map {
                push_indent(out, level);
                out.push_str(&yaml_string(key));
                out.push(':');
                emit_after_key(out, item, level);
            }
        }
        Json::Array(items) if !items.is_empty() => {
            for item in items {
                push_indent(out, level);
                out.push_str("- ");
                emit_after_dash(out, item, level);
            }
        }
        other => {
            push_indent(out, level);
            out.push_str(&scalar(other));
            out.push('\n');
        }
    }
}

/// Cursor is immediately after `key:`.
fn emit_after_key(out: &mut String, value: &Json, level: usize) {
    match value {
        Json::Object(map) if !map.is_empty() => {
            out.push('\n');
            emit_block(out, &Json::Object(map.clone()), level + 1);
        }
        Json::Array(items) if !items.is_empty() => {
            out.push('\n');
            emit_block(out, &Json::Array(items.clone()), level + 1);
        }
        other => {
            out.push(' ');
            out.push_str(&scalar(other));
            out.push('\n');
        }
    }
}

/// Cursor is immediately after `- `.
fn emit_after_dash(out: &mut String, value: &Json, level: usize) {
    match value {
        Json::Object(map) if !map.is_empty() => {
            // First key continues the `- ` line; later keys align with it.
            for (index, (key, item)) in map.iter().enumerate() {
                if index > 0 {
                    push_indent(out, level + 1);
                }
                out.push_str(&yaml_string(key));
                out.push(':');
                emit_after_key(out, item, level + 1);
            }
        }
        Json::Array(items) if !items.is_empty() => {
            out.push('\n');
            emit_block(out, &Json::Array(items.clone()), level + 1);
        }
        other => {
            out.push_str(&scalar(other));
            out.push('\n');
        }
    }
}

fn push_indent(out: &mut String, level: usize) {
    for _ in 0..level {
        out.push_str("  ");
    }
}

fn scalar(value: &Json) -> String {
    match value {
        Json::Null => "null".to_string(),
        Json::Bool(true) => "true".to_string(),
        Json::Bool(false) => "false".to_string(),
        Json::Number(number) => number.as_text().to_string(),
        Json::String(text) => yaml_string(text),
        Json::Array(_) => "[]".to_string(),
        Json::Object(_) => "{}".to_string(),
    }
}

fn yaml_string(text: &str) -> String {
    let mut out = String::with_capacity(text.len() + 2);
    out.push('"');
    for character in text.chars() {
        match character {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            control if (control as u32) < 0x20 => {
                out.push_str(&format!("\\x{:02x}", control as u32));
            }
            other => out.push(other),
        }
    }
    out.push('"');
    out
}

#[cfg(test)]
mod tests {
    use super::{parse, to_yaml};
    use crate::json::{compact, Json, Number};

    #[test]
    fn parses_contract_shaped_yaml() {
        let text = "version: 1.1\npermissions:\n  - github:issues:read\napprovals: []\nprovisional: true\n";
        let value = parse(text).unwrap();
        assert_eq!(compact(&value), "{\"approvals\":[],\"permissions\":[\"github:issues:read\"],\"provisional\":true,\"version\":1.1}");
    }

    #[test]
    fn rejects_non_string_keys_and_multiple_documents() {
        assert!(parse("1: value\n").is_err());
        assert!(parse("a: 1\n---\nb: 2\n").is_err());
    }

    #[test]
    fn round_trips_through_the_emitter() {
        let value = Json::from_pairs([
            (
                "side_effects",
                Json::Array(vec![Json::from_pairs([
                    ("resource", Json::String("github".to_string())),
                    ("type", Json::String("comment".to_string())),
                ])]),
            ),
            ("version", Json::Number(Number::new("1.2"))),
            ("empty", Json::Array(vec![])),
            ("nested", Json::from_pairs([("a", Json::Null)])),
            ("text", Json::String("a: b \"quoted\"\n".to_string())),
        ]);
        let emitted = to_yaml(&value);
        let reparsed = parse(&emitted).unwrap();
        assert_eq!(reparsed, value, "emitted YAML:\n{emitted}");
    }
}
