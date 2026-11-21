//! UTC ISO-8601 timestamps for audit entries.
//!
//! Vectors never assert a timestamp (`vectors/README.md`: "no wall clock"), so
//! this module exists only to make `gate --audit` output and trace-derived
//! entries readable. It deliberately has no timezone database: everything is
//! UTC, formatted from the Unix epoch with the civil-from-days algorithm.

use std::time::{SystemTime, UNIX_EPOCH};

/// Current UTC time as `YYYY-MM-DDTHH:MM:SS.ffffffZ`.
pub fn now_iso8601() -> String {
    let duration = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default();
    iso8601_from_unix(duration.as_secs() as i64, duration.subsec_micros())
}

/// Format a Unix timestamp (seconds + microseconds) as ISO-8601 UTC.
pub fn iso8601_from_unix(seconds: i64, micros: u32) -> String {
    let days = seconds.div_euclid(86_400);
    let seconds_of_day = seconds.rem_euclid(86_400);
    let (year, month, day) = civil_from_days(days);
    let hour = seconds_of_day / 3_600;
    let minute = (seconds_of_day % 3_600) / 60;
    let second = seconds_of_day % 60;
    format!("{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}.{micros:06}Z")
}

/// Howard Hinnant's `civil_from_days`: days since 1970-01-01 to a proleptic
/// Gregorian date. Valid for the whole `i64` range the formatter can receive.
fn civil_from_days(days: i64) -> (i64, u32, u32) {
    let shifted = days + 719_468;
    let era = if shifted >= 0 {
        shifted
    } else {
        shifted - 146_096
    } / 146_097;
    let day_of_era = (shifted - era * 146_097) as u64; // [0, 146096]
    let year_of_era =
        (day_of_era - day_of_era / 1_460 + day_of_era / 36_524 - day_of_era / 146_096) / 365;
    let year = year_of_era as i64 + era * 400;
    let day_of_year = day_of_era - (365 * year_of_era + year_of_era / 4 - year_of_era / 100);
    let month_prime = (5 * day_of_year + 2) / 153;
    let day = (day_of_year - (153 * month_prime + 2) / 5 + 1) as u32;
    let month = if month_prime < 10 {
        month_prime + 3
    } else {
        month_prime - 9
    } as u32;
    let year = if month <= 2 { year + 1 } else { year };
    (year, month, day)
}

#[cfg(test)]
mod tests {
    use super::iso8601_from_unix;

    #[test]
    fn formats_epoch_and_known_instants() {
        assert_eq!(iso8601_from_unix(0, 0), "1970-01-01T00:00:00.000000Z");
        assert_eq!(
            iso8601_from_unix(1_700_000_000, 123_456),
            "2023-11-14T22:13:20.123456Z"
        );
        assert_eq!(
            iso8601_from_unix(1_780_000_000, 1),
            "2026-05-28T20:26:40.000001Z"
        );
    }

    #[test]
    fn handles_leap_days() {
        assert_eq!(
            iso8601_from_unix(951_782_400, 0),
            "2000-02-29T00:00:00.000000Z"
        );
        assert_eq!(
            iso8601_from_unix(1_709_164_800, 0),
            "2024-02-29T00:00:00.000000Z"
        );
    }
}
