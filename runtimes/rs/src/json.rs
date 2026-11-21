//! Minimal JSON value, a fail-closed parser, and Python-compatible canonical
//! writers.
//!
//! The runtime deliberately does not depend on a JSON crate. Two reasons:
//!
//! 1. **The bytes are the contract.** RFC 0005 §6.3/§6.8 pin canonical forms
//!    that the Python reference produces with `json.dumps(...)`: sorted keys,
//!    `ensure_ascii=True` for vector files and results, `ensure_ascii=False`
//!    for trace JSONL. Reproducing those exactly is easier with a writer we own
//!    than with a general-purpose serializer.
//! 2. **Duplicate keys fail closed.** The reference loader rejects duplicate
//!    JSON object keys outright (`object_pairs_hook`), which a standard
//!    last-one-wins parser would silently accept.
//!
//! Object keys are stored in a `BTreeMap`, so iteration is already sorted by
//! Unicode code point — the same order Python's `sort_keys=True` uses.

use std::collections::BTreeMap;
use std::fmt;

/// A JSON number kept as its original literal text.
///
/// Preserving the literal keeps canonical output byte-identical to the input
/// (`1.10` stays `1.10`), and numeric comparison still works through
/// [`Number::as_f64`].
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Number {
    raw: String,
}

impl Number {
    pub fn new(raw: impl Into<String>) -> Self {
        Number { raw: raw.into() }
    }

    pub fn as_text(&self) -> &str {
        &self.raw
    }

    pub fn as_i64(&self) -> Option<i64> {
        self.raw.parse::<i64>().ok()
    }

    pub fn as_f64(&self) -> Option<f64> {
        self.raw.parse::<f64>().ok()
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Json {
    Null,
    Bool(bool),
    Number(Number),
    String(String),
    Array(Vec<Json>),
    Object(BTreeMap<String, Json>),
}

impl Json {
    pub fn object() -> BTreeMap<String, Json> {
        BTreeMap::new()
    }

    pub fn from_object(entries: BTreeMap<String, Json>) -> Json {
        Json::Object(entries)
    }

    pub fn from_pairs<I, K>(pairs: I) -> Json
    where
        I: IntoIterator<Item = (K, Json)>,
        K: Into<String>,
    {
        let mut map = BTreeMap::new();
        for (key, value) in pairs {
            map.insert(key.into(), value);
        }
        Json::Object(map)
    }

    pub fn as_str(&self) -> Option<&str> {
        match self {
            Json::String(value) => Some(value),
            _ => None,
        }
    }

    pub fn as_bool(&self) -> Option<bool> {
        match self {
            Json::Bool(value) => Some(*value),
            _ => None,
        }
    }

    pub fn as_array(&self) -> Option<&Vec<Json>> {
        match self {
            Json::Array(value) => Some(value),
            _ => None,
        }
    }

    pub fn as_object(&self) -> Option<&BTreeMap<String, Json>> {
        match self {
            Json::Object(value) => Some(value),
            _ => None,
        }
    }

    pub fn get(&self, key: &str) -> Option<&Json> {
        self.as_object().and_then(|map| map.get(key))
    }

    pub fn is_object(&self) -> bool {
        matches!(self, Json::Object(_))
    }

    pub fn kind(&self) -> &'static str {
        match self {
            Json::Null => "null",
            Json::Bool(_) => "boolean",
            Json::Number(_) => "number",
            Json::String(_) => "string",
            Json::Array(_) => "array",
            Json::Object(_) => "object",
        }
    }
}

// ---------------------------------------------------------------------------
// Parsing
// ---------------------------------------------------------------------------

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct JsonError {
    message: String,
}

impl JsonError {
    pub fn new(message: impl Into<String>) -> Self {
        JsonError {
            message: message.into(),
        }
    }

    pub fn message(&self) -> &str {
        &self.message
    }
}

impl fmt::Display for JsonError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl std::error::Error for JsonError {}

const MAX_DEPTH: usize = 128;

struct Parser<'a> {
    bytes: &'a [u8],
    input: &'a str,
    pos: usize,
    depth: usize,
}

/// Parse one JSON document, rejecting duplicate object keys and trailing data.
pub fn parse(text: &str) -> Result<Json, JsonError> {
    let mut parser = Parser {
        bytes: text.as_bytes(),
        input: text,
        pos: 0,
        depth: 0,
    };
    let value = parser.parse_value()?;
    parser.skip_whitespace();
    if parser.pos != parser.bytes.len() {
        return Err(parser.fail(format!("trailing data at position {}", parser.pos)));
    }
    Ok(value)
}

impl<'a> Parser<'a> {
    fn fail(&self, message: impl Into<String>) -> JsonError {
        JsonError::new(message)
    }

    fn remaining(&self) -> Option<char> {
        self.input[self.pos..].chars().next()
    }

    fn skip_whitespace(&mut self) {
        while let Some(character) = self.remaining() {
            match character {
                ' ' | '\t' | '\n' | '\r' => self.pos += character.len_utf8(),
                _ => break,
            }
        }
    }

    fn parse_value(&mut self) -> Result<Json, JsonError> {
        self.skip_whitespace();
        let character = match self.remaining() {
            Some(character) => character,
            None => return Err(self.fail("unexpected end of JSON input")),
        };
        match character {
            '"' => Ok(Json::String(self.parse_string()?)),
            '{' => self.parse_object(),
            '[' => self.parse_array(),
            't' => {
                self.expect_keyword("true")?;
                Ok(Json::Bool(true))
            }
            'f' => {
                self.expect_keyword("false")?;
                Ok(Json::Bool(false))
            }
            'n' => {
                self.expect_keyword("null")?;
                Ok(Json::Null)
            }
            '-' | '0'..='9' => self.parse_number(),
            other => Err(self.fail(format!(
                "unexpected character '{other}' at position {}",
                self.pos
            ))),
        }
    }

    fn expect_keyword(&mut self, keyword: &str) -> Result<(), JsonError> {
        if self.input[self.pos..].starts_with(keyword) {
            self.pos += keyword.len();
            Ok(())
        } else {
            Err(self.fail(format!(
                "unexpected character '{}' at position {}",
                self.remaining().unwrap_or('\0'),
                self.pos
            )))
        }
    }

    fn enter(&mut self) -> Result<(), JsonError> {
        self.depth += 1;
        if self.depth > MAX_DEPTH {
            return Err(self.fail(format!("JSON nesting deeper than {MAX_DEPTH} levels")));
        }
        Ok(())
    }

    fn parse_object(&mut self) -> Result<Json, JsonError> {
        self.enter()?;
        self.pos += 1; // '{'
        self.skip_whitespace();
        let mut result: BTreeMap<String, Json> = BTreeMap::new();
        if self.remaining() == Some('}') {
            self.pos += 1;
            self.depth -= 1;
            return Ok(Json::Object(result));
        }
        loop {
            self.skip_whitespace();
            let key = self.parse_string()?;
            if result.contains_key(&key) {
                return Err(self.fail(format!("duplicate JSON key '{key}'")));
            }
            self.skip_whitespace();
            if self.remaining() != Some(':') {
                return Err(self.fail(format!(
                    "expected ':' after object key at position {}",
                    self.pos
                )));
            }
            self.pos += 1;
            let value = self.parse_value()?;
            result.insert(key, value);
            self.skip_whitespace();
            match self.remaining() {
                Some(',') => {
                    self.pos += 1;
                }
                Some('}') => {
                    self.pos += 1;
                    self.depth -= 1;
                    return Ok(Json::Object(result));
                }
                _ => {
                    return Err(self.fail(format!("expected ',' or '}}' at position {}", self.pos)))
                }
            }
        }
    }

    fn parse_array(&mut self) -> Result<Json, JsonError> {
        self.enter()?;
        self.pos += 1; // '['
        self.skip_whitespace();
        let mut result: Vec<Json> = Vec::new();
        if self.remaining() == Some(']') {
            self.pos += 1;
            self.depth -= 1;
            return Ok(Json::Array(result));
        }
        loop {
            result.push(self.parse_value()?);
            self.skip_whitespace();
            match self.remaining() {
                Some(',') => {
                    self.pos += 1;
                }
                Some(']') => {
                    self.pos += 1;
                    self.depth -= 1;
                    return Ok(Json::Array(result));
                }
                _ => return Err(self.fail(format!("expected ',' or ']' at position {}", self.pos))),
            }
        }
    }

    fn parse_string(&mut self) -> Result<String, JsonError> {
        if self.remaining() != Some('"') {
            return Err(self.fail(format!("expected a string at position {}", self.pos)));
        }
        self.pos += 1;
        let mut output = String::new();
        loop {
            let character = match self.remaining() {
                Some(character) => character,
                None => return Err(self.fail("unterminated string")),
            };
            self.pos += character.len_utf8();
            match character {
                '"' => return Ok(output),
                '\\' => {
                    let escape = match self.remaining() {
                        Some(escape) => escape,
                        None => return Err(self.fail("unterminated string")),
                    };
                    self.pos += escape.len_utf8();
                    match escape {
                        '"' => output.push('"'),
                        '\\' => output.push('\\'),
                        '/' => output.push('/'),
                        'b' => output.push('\u{8}'),
                        'f' => output.push('\u{c}'),
                        'n' => output.push('\n'),
                        'r' => output.push('\r'),
                        't' => output.push('\t'),
                        'u' => output.push(self.parse_unicode_escape()?),
                        _ => {
                            return Err(self.fail("invalid escape sequence in string"));
                        }
                    }
                }
                control if (control as u32) < 0x20 => {
                    return Err(self.fail("unescaped control character in string"));
                }
                other => output.push(other),
            }
        }
    }

    fn parse_hex4(&mut self) -> Result<u32, JsonError> {
        if self.pos + 4 > self.bytes.len() {
            return Err(self.fail("invalid unicode escape in string"));
        }
        let slice = &self.input[self.pos..self.pos + 4];
        if !slice.bytes().all(|byte| byte.is_ascii_hexdigit()) {
            return Err(self.fail("invalid unicode escape in string"));
        }
        self.pos += 4;
        u32::from_str_radix(slice, 16).map_err(|_| self.fail("invalid unicode escape in string"))
    }

    fn parse_unicode_escape(&mut self) -> Result<char, JsonError> {
        let first = self.parse_hex4()?;
        if (0xd800..=0xdbff).contains(&first) {
            if !self.input[self.pos..].starts_with("\\u") {
                return Err(self.fail("lone high surrogate in string escape"));
            }
            self.pos += 2;
            let second = self.parse_hex4()?;
            if !(0xdc00..=0xdfff).contains(&second) {
                return Err(self.fail("invalid low surrogate in string escape"));
            }
            let combined = 0x10000 + ((first - 0xd800) << 10) + (second - 0xdc00);
            return char::from_u32(combined)
                .ok_or_else(|| self.fail("invalid unicode escape in string"));
        }
        if (0xdc00..=0xdfff).contains(&first) {
            return Err(self.fail("lone low surrogate in string escape"));
        }
        char::from_u32(first).ok_or_else(|| self.fail("invalid unicode escape in string"))
    }

    fn parse_number(&mut self) -> Result<Json, JsonError> {
        let start = self.pos;
        let bytes = self.bytes;
        if self.pos < bytes.len() && bytes[self.pos] == b'-' {
            self.pos += 1;
        }
        // int part
        match bytes.get(self.pos) {
            Some(b'0') => self.pos += 1,
            Some(byte) if byte.is_ascii_digit() => {
                while matches!(bytes.get(self.pos), Some(byte) if byte.is_ascii_digit()) {
                    self.pos += 1;
                }
            }
            _ => return Err(self.fail(format!("invalid number at position {}", self.pos))),
        }
        // fraction
        if bytes.get(self.pos) == Some(&b'.') {
            self.pos += 1;
            let digits_start = self.pos;
            while matches!(bytes.get(self.pos), Some(byte) if byte.is_ascii_digit()) {
                self.pos += 1;
            }
            if digits_start == self.pos {
                return Err(self.fail(format!("invalid number at position {}", self.pos)));
            }
        }
        // exponent
        if matches!(bytes.get(self.pos), Some(b'e') | Some(b'E')) {
            self.pos += 1;
            if matches!(bytes.get(self.pos), Some(b'+') | Some(b'-')) {
                self.pos += 1;
            }
            let digits_start = self.pos;
            while matches!(bytes.get(self.pos), Some(byte) if byte.is_ascii_digit()) {
                self.pos += 1;
            }
            if digits_start == self.pos {
                return Err(self.fail(format!("invalid number at position {}", self.pos)));
            }
        }
        let raw = &self.input[start..self.pos];
        let number = Number::new(raw);
        let finite = number.as_f64().is_some_and(f64::is_finite);
        if !finite {
            return Err(self.fail("number is not finite"));
        }
        Ok(Json::Number(number))
    }
}

// ---------------------------------------------------------------------------
// Canonical output (Python-compatible)
// ---------------------------------------------------------------------------

fn write_escaped(out: &mut String, value: &str, ensure_ascii: bool) {
    out.push('"');
    for character in value.chars() {
        match character {
            '"' => out.push_str("\\\""),
            '\\' => out.push_str("\\\\"),
            '\u{8}' => out.push_str("\\b"),
            '\u{c}' => out.push_str("\\f"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            control if (control as u32) < 0x20 => {
                out.push_str(&format!("\\u{:04x}", control as u32));
            }
            other if ensure_ascii && (other as u32) > 0x7f => {
                let code = other as u32;
                if code <= 0xffff {
                    out.push_str(&format!("\\u{code:04x}"));
                } else {
                    let value = code - 0x10000;
                    let high = 0xd800 + (value >> 10);
                    let low = 0xdc00 + (value & 0x3ff);
                    out.push_str(&format!("\\u{high:04x}\\u{low:04x}"));
                }
            }
            other => out.push(other),
        }
    }
    out.push('"');
}

fn write_compact(out: &mut String, value: &Json, ensure_ascii: bool) {
    match value {
        Json::Null => out.push_str("null"),
        Json::Bool(true) => out.push_str("true"),
        Json::Bool(false) => out.push_str("false"),
        Json::Number(number) => out.push_str(number.as_text()),
        Json::String(text) => write_escaped(out, text, ensure_ascii),
        Json::Array(items) => {
            out.push('[');
            for (index, item) in items.iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }
                write_compact(out, item, ensure_ascii);
            }
            out.push(']');
        }
        Json::Object(entries) => {
            out.push('{');
            for (index, (key, item)) in entries.iter().enumerate() {
                if index > 0 {
                    out.push(',');
                }
                write_escaped(out, key, ensure_ascii);
                out.push(':');
                write_compact(out, item, ensure_ascii);
            }
            out.push('}');
        }
    }
}

fn indent(out: &mut String, level: usize) {
    for _ in 0..level {
        out.push_str("  ");
    }
}

fn write_pretty(out: &mut String, value: &Json, level: usize) {
    match value {
        Json::Array(items) if !items.is_empty() => {
            out.push_str("[\n");
            for (index, item) in items.iter().enumerate() {
                indent(out, level + 1);
                write_pretty(out, item, level + 1);
                if index + 1 < items.len() {
                    out.push(',');
                }
                out.push('\n');
            }
            indent(out, level);
            out.push(']');
        }
        Json::Object(entries) if !entries.is_empty() => {
            out.push_str("{\n");
            for (index, (key, item)) in entries.iter().enumerate() {
                indent(out, level + 1);
                write_escaped(out, key, true);
                out.push_str(": ");
                write_pretty(out, item, level + 1);
                if index + 1 < entries.len() {
                    out.push(',');
                }
                out.push('\n');
            }
            indent(out, level);
            out.push('}');
        }
        other => write_compact(out, other, true),
    }
}

/// Sorted keys, compact separators, `ensure_ascii=True` (vector results).
pub fn compact(value: &Json) -> String {
    let mut out = String::new();
    write_compact(&mut out, value, true);
    out
}

/// Sorted keys, compact separators, UTF-8 preserved (trace JSONL).
pub fn compact_utf8(value: &Json) -> String {
    let mut out = String::new();
    write_compact(&mut out, value, false);
    out
}

/// Sorted keys, two-space indent, `ensure_ascii=True`, one trailing newline
/// (canonical vector files).
pub fn pretty(value: &Json) -> String {
    let mut out = String::new();
    write_pretty(&mut out, value, 0);
    out.push('\n');
    out
}

// ---------------------------------------------------------------------------
// Structural comparison
// ---------------------------------------------------------------------------

/// JSON equality with numeric comparison, mirroring Python's `==` on parsed
/// documents (`1 == 1.0`). Used by `const`/`enum`/`uniqueItems` validation.
pub fn json_equal(left: &Json, right: &Json) -> bool {
    match (left, right) {
        (Json::Null, Json::Null) => true,
        (Json::Bool(a), Json::Bool(b)) => a == b,
        (Json::String(a), Json::String(b)) => a == b,
        (Json::Number(a), Json::Number(b)) => match (a.as_f64(), b.as_f64()) {
            (Some(x), Some(y)) => x == y,
            _ => a.as_text() == b.as_text(),
        },
        (Json::Array(a), Json::Array(b)) => {
            a.len() == b.len() && a.iter().zip(b.iter()).all(|(x, y)| json_equal(x, y))
        }
        (Json::Object(a), Json::Object(b)) => {
            a.len() == b.len()
                && a.iter()
                    .all(|(key, value)| b.get(key).is_some_and(|other| json_equal(value, other)))
        }
        _ => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn object(pairs: &[(&str, Json)]) -> Json {
        let mut map = BTreeMap::new();
        for (key, value) in pairs {
            map.insert((*key).to_string(), value.clone());
        }
        Json::Object(map)
    }

    #[test]
    fn parses_and_rejects_duplicate_keys() {
        assert_eq!(
            parse("{\"b\":1,\"a\":[true,null]}").unwrap(),
            object(&[
                ("a", Json::Array(vec![Json::Bool(true), Json::Null])),
                ("b", Json::Number(Number::new("1")))
            ])
        );
        let error = parse("{\"a\":1,\"a\":2}").unwrap_err();
        assert!(error.message().contains("duplicate JSON key 'a'"));
    }

    #[test]
    fn rejects_trailing_data_and_bad_numbers() {
        assert!(parse("{} x").is_err());
        assert!(parse("01").is_err());
        assert!(parse("1.").is_err());
        assert!(parse("\"\\ud800\"").is_err());
        assert_eq!(parse("1e3").unwrap(), Json::Number(Number::new("1e3")));
    }

    #[test]
    fn canonical_compact_matches_python() {
        let value = object(&[
            ("b", Json::String("é".to_string())),
            ("a", Json::Array(vec![Json::Number(Number::new("1"))])),
        ]);
        assert_eq!(compact(&value), "{\"a\":[1],\"b\":\"\\u00e9\"}");
        assert_eq!(compact_utf8(&value), "{\"a\":[1],\"b\":\"é\"}");
    }

    #[test]
    fn canonical_pretty_matches_python_indent() {
        let value = object(&[
            (
                "a",
                Json::Array(vec![Json::Number(Number::new("1")), Json::Null]),
            ),
            ("b", object(&[])),
        ]);
        assert_eq!(
            pretty(&value),
            "{\n  \"a\": [\n    1,\n    null\n  ],\n  \"b\": {}\n}\n"
        );
    }

    #[test]
    fn escapes_astral_characters_as_surrogate_pairs() {
        let value = Json::String("\u{1f600}".to_string());
        assert_eq!(compact(&value), "\"\\ud83d\\ude00\"");
        assert_eq!(compact_utf8(&value), "\"\u{1f600}\"");
    }

    #[test]
    fn numbers_compare_numerically() {
        assert!(json_equal(
            &Json::Number(Number::new("1")),
            &Json::Number(Number::new("1.0"))
        ));
        assert!(!json_equal(
            &Json::Number(Number::new("1")),
            &Json::String("1".to_string())
        ));
    }
}
