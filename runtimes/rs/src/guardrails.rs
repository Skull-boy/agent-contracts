//! RFC 0003 §C5 guardrails (v1.2) — the portable subset.
//!
//! Counters are per enforcer instance and per process. They bound one runtime's
//! behavior; they are not a distributed quota. This matches the Python
//! reference's documented limitation.

use crate::errors::Error;
use crate::json::Json;

pub const RATE_LIMIT_WINDOW_SECONDS: i64 = 60;
pub const FAIL_CLOSED_FIELD_REFERENCE: &str = "guardrails.fail_closed";
pub const BUDGETS_FIELD_REFERENCE: &str = "guardrails.budgets";
pub const RATE_LIMIT_FIELD_REFERENCE: &str = "guardrails.rate_limit";

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Budgets {
    pub side_effects_per_window: i64,
    pub window: String,
    pub window_seconds: i64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RateLimit {
    pub max_calls_per_minute: i64,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Guardrails {
    pub fail_closed: bool,
    pub budgets: Option<Budgets>,
    pub rate_limit: Option<RateLimit>,
}

/// Parse a window literal like `30m`, `1h`, `7d` into seconds.
pub fn parse_window(value: &Json) -> Result<i64, Error> {
    let text = match value {
        Json::String(text) => text,
        other => {
            return Err(Error::validation(format!(
                "guardrails window must be a string like '1h', got {}",
                other.kind()
            )))
        }
    };
    let Some(unit) = text.chars().last() else {
        return Err(Error::validation(format!(
            "guardrails window '{text}' must match ^[0-9]+(s|m|h|d)$ (examples: '30m', '1h', '7d')"
        )));
    };
    let multiplier = match unit {
        's' => 1,
        'm' => 60,
        'h' => 60 * 60,
        'd' => 24 * 60 * 60,
        _ => {
            return Err(Error::validation(format!(
            "guardrails window '{text}' must match ^[0-9]+(s|m|h|d)$ (examples: '30m', '1h', '7d')"
        )))
        }
    };
    let digits = &text[..text.len() - unit.len_utf8()];
    if digits.is_empty() || !digits.chars().all(|character| character.is_ascii_digit()) {
        return Err(Error::validation(format!(
            "guardrails window '{text}' must match ^[0-9]+(s|m|h|d)$ (examples: '30m', '1h', '7d')"
        )));
    }
    let amount: i64 = digits
        .parse()
        .map_err(|_| Error::validation(format!("guardrails window '{text}' is too large")))?;
    if amount <= 0 {
        return Err(Error::validation(format!(
            "guardrails window '{text}' must be greater than zero"
        )));
    }
    Ok(amount * multiplier)
}

fn require_mapping<'a>(
    value: &'a Json,
    field: &str,
) -> Result<&'a std::collections::BTreeMap<String, Json>, Error> {
    value.as_object().ok_or_else(|| {
        Error::validation(format!(
            "guardrails.{field} must be an object, got {}",
            value.kind()
        ))
    })
}

fn require_positive_int(value: &Json, field: &str) -> Result<i64, Error> {
    let parsed = match value {
        Json::Number(number) => number.as_f64(),
        _ => None,
    };
    match parsed {
        Some(number) if number.fract() == 0.0 && number >= 1.0 => Ok(number as i64),
        _ => Err(Error::validation(format!(
            "guardrails.{field} must be an integer >= 1, got {}",
            value.kind()
        ))),
    }
}

fn reject_unknown(
    map: &std::collections::BTreeMap<String, Json>,
    allowed: &[&str],
    field: &str,
) -> Result<(), Error> {
    let unknown: Vec<&str> = map
        .keys()
        .map(String::as_str)
        .filter(|key| !allowed.contains(key))
        .collect();
    if unknown.is_empty() {
        Ok(())
    } else {
        Err(Error::validation(format!(
            "guardrails.{field} has unknown key(s): {}",
            unknown.join(", ")
        )))
    }
}

/// Parse the optional top-level `guardrails` block.
///
/// Returns `None` when the key is absent or null (matching the Python
/// reference), and an explicit no-op record for `{}`.
pub fn parse_guardrails(raw: Option<&Json>) -> Result<Option<Guardrails>, Error> {
    let raw = match raw {
        None | Some(Json::Null) => return Ok(None),
        Some(value) => value,
    };

    let map = require_mapping(raw, "<root>")?;
    reject_unknown(map, &["fail_closed", "budgets", "rate_limit"], "<root>")?;

    let fail_closed = match map.get("fail_closed") {
        None => false,
        Some(Json::Bool(flag)) => *flag,
        Some(other) => {
            return Err(Error::validation(format!(
                "guardrails.fail_closed must be a boolean, got {}",
                other.kind()
            )))
        }
    };

    let budgets = match map.get("budgets") {
        None => None,
        Some(raw_budgets) => {
            let budgets_map = require_mapping(raw_budgets, "budgets")?;
            reject_unknown(
                budgets_map,
                &["side_effects_per_window", "window"],
                "budgets",
            )?;
            let limit = budgets_map.get("side_effects_per_window").ok_or_else(|| {
                Error::validation("guardrails.budgets requires 'side_effects_per_window'")
            })?;
            let window = budgets_map
                .get("window")
                .ok_or_else(|| Error::validation("guardrails.budgets requires 'window'"))?;
            let window_text = match window {
                Json::String(text) => text.clone(),
                other => crate::json::compact(other),
            };
            Some(Budgets {
                side_effects_per_window: require_positive_int(
                    limit,
                    "budgets.side_effects_per_window",
                )?,
                window: window_text,
                window_seconds: parse_window(window)?,
            })
        }
    };

    let rate_limit = match map.get("rate_limit") {
        None => None,
        Some(raw_rate) => {
            let rate_map = require_mapping(raw_rate, "rate_limit")?;
            reject_unknown(rate_map, &["max_calls_per_minute"], "rate_limit")?;
            let limit = rate_map.get("max_calls_per_minute").ok_or_else(|| {
                Error::validation("guardrails.rate_limit requires 'max_calls_per_minute'")
            })?;
            Some(RateLimit {
                max_calls_per_minute: require_positive_int(
                    limit,
                    "rate_limit.max_calls_per_minute",
                )?,
            })
        }
    };

    Ok(Some(Guardrails {
        fail_closed,
        budgets,
        rate_limit,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::yaml;

    fn value(source: &str) -> Json {
        yaml::parse(source).unwrap()
    }

    #[test]
    fn parses_the_vector_guardrail_block() {
        let parsed = parse_guardrails(Some(&value(
            "budgets:\n  side_effects_per_window: 1\n  window: \"1h\"\n",
        )))
        .unwrap()
        .unwrap();
        assert!(!parsed.fail_closed);
        assert_eq!(
            parsed.budgets,
            Some(Budgets {
                side_effects_per_window: 1,
                window: "1h".to_string(),
                window_seconds: 3_600,
            })
        );
        assert_eq!(parsed.rate_limit, None);
    }

    #[test]
    fn rejects_unknown_keys_and_bad_windows() {
        assert!(parse_guardrails(Some(&value("nope: true\n"))).is_err());
        assert!(parse_guardrails(Some(&value(
            "budgets:\n  side_effects_per_window: 1\n  window: \"one hour\"\n"
        )))
        .is_err());
        assert!(parse_guardrails(Some(&value(
            "budgets:\n  side_effects_per_window: 0\n  window: \"1h\"\n"
        )))
        .is_err());
    }

    #[test]
    fn absent_and_null_are_distinct_from_empty() {
        assert_eq!(parse_guardrails(None).unwrap(), None);
        assert_eq!(parse_guardrails(Some(&Json::Null)).unwrap(), None);
        assert!(parse_guardrails(Some(&value("{}"))).unwrap().is_some());
    }
}
