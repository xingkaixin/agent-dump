use jiff::{SignedDuration, civil::DateTime, tz::TimeZone};
use std::fmt::Write as _;
use std::str::FromStr;
use std::time::SystemTime;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct Timestamp(DateTime);

impl Timestamp {
    pub const UNIX_EPOCH: Self =
        Self(jiff::civil::date(1970, 1, 1).at(0, 0, 0, 0));
    pub fn now() -> Self {
        Self(
            jiff::Timestamp::now()
                .to_zoned_datetime(TimeZone::UTC)
                .datetime(),
        )
    }

    pub fn days_ago(days: i64) -> crate::Result<Self> {
        Self::now().checked_sub(SignedDuration::from_secs(
            days.checked_mul(86400).ok_or("days is out of range")?,
        ))
    }

    pub fn from_microsecond(micros: i64) -> crate::Result<Self> {
        Self::checked(
            Self::UNIX_EPOCH
                .0
                .checked_add(SignedDuration::from_micros(micros))?,
        )
    }

    pub fn from_nanosecond(nanos: i128) -> crate::Result<Self> {
        Self::from_microsecond(i64::try_from(nanos / 1_000)?)
    }

    fn checked(value: DateTime) -> crate::Result<Self> {
        if value.year() < 1 {
            return Err(crate::providers::error::ProviderError::Cause {
                kind: "OverflowError",
                message: "date value out of range".into(),
            }
            .into());
        }
        Ok(Self(value))
    }

    pub fn checked_sub(self, duration: SignedDuration) -> crate::Result<Self> {
        Self::checked(self.0.checked_sub(duration)?)
    }
    pub fn as_microsecond(self) -> i64 {
        i64::try_from(self.0.duration_since(Self::UNIX_EPOCH.0).as_micros())
            .expect("civil datetime microseconds fit in i64")
    }
    pub fn iso_utc(self) -> String {
        let mut out = String::with_capacity(32);
        let d = self.0;
        let _ = write!(
            out,
            "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}.{:06}+00:00",
            d.year(),
            d.month(),
            d.day(),
            d.hour(),
            d.minute(),
            d.second(),
            d.subsec_nanosecond() / 1_000
        );
        out
    }

    fn to_local_zoned(self) -> (jiff::ZonedDateTime, i16) {
        let zone = TimeZone::system();
        if let Ok(timestamp) =
            jiff::Timestamp::from_microsecond(self.as_microsecond())
        {
            return (timestamp.to_zoned_datetime(zone), 0);
        }
        // Jiff reserves 26 hours at each timestamp boundary for zone conversion.
        // Far-future IANA rules repeat with the 400-year Gregorian calendar cycle.
        let shifted = self.0.with().year(self.0.year() - 400).build().unwrap();
        let local = shifted
            .to_zoned_datetime(TimeZone::UTC)
            .unwrap()
            .with_time_zone(zone);
        (local, 400)
    }

    pub fn local_date(self) -> jiff::civil::Date {
        let (local, shift) = self.to_local_zoned();
        if shift == 0 {
            local.date()
        } else {
            jiff::civil::Date::new(
                local.year() + shift,
                local.month(),
                local.day(),
            )
            .unwrap()
        }
    }

    pub fn iso_local(self) -> String {
        let (local, shift) = self.to_local_zoned();
        let year = local.year() + shift;
        let micros = self.0.subsec_nanosecond() / 1_000;
        let offset = local.offset().seconds();
        let sign = if offset < 0 { '-' } else { '+' };
        let abs = offset.unsigned_abs();
        let oh = abs / 3600;
        let om = (abs % 3600) / 60;
        let mut result = String::with_capacity(32);
        if cfg!(all(target_os = "linux", target_env = "gnu")) && shift == 0 {
            let _ = write!(
                result,
                "{}-{:02}-{:02}T{:02}:{:02}:{:02}",
                year,
                local.month(),
                local.day(),
                local.hour(),
                local.minute(),
                local.second(),
            );
        } else {
            let _ = write!(
                result,
                "{:04}-{:02}-{:02}T{:02}:{:02}:{:02}",
                year,
                local.month(),
                local.day(),
                local.hour(),
                local.minute(),
                local.second(),
            );
        }
        if micros != 0 {
            let _ = write!(result, ".{micros:06}");
        }
        let _ = write!(result, "{sign}{oh:02}:{om:02}");
        result
    }
    #[allow(
        clippy::cast_possible_truncation,
        clippy::cast_precision_loss,
        reason = "Exported milliseconds must preserve Python floating-point rounding"
    )]
    pub fn as_millisecond(self) -> i64 {
        // Python exports int(datetime.timestamp() * 1000), including float rounding.
        (self.as_microsecond() as f64 / 1_000_000.0 * 1_000.0) as i64
    }
    pub fn format_local(self, format: &str) -> String {
        let (local, shift) = self.to_local_zoned();
        if format == "%Y-%m-%d %H:%M" {
            let year = local.year() + shift;
            let mut out = String::with_capacity(16);
            if cfg!(all(target_os = "linux", target_env = "gnu")) && shift == 0
            {
                let _ = write!(
                    out,
                    "{}-{:02}-{:02} {:02}:{:02}",
                    year,
                    local.month(),
                    local.day(),
                    local.hour(),
                    local.minute()
                );
            } else {
                let _ = write!(
                    out,
                    "{:04}-{:02}-{:02} {:02}:{:02}",
                    year,
                    local.month(),
                    local.day(),
                    local.hour(),
                    local.minute()
                );
            }
            return out;
        }
        if shift == 0 {
            // CPython delegates %Y padding to libc; glibc does not pad small years.
            if cfg!(all(target_os = "linux", target_env = "gnu")) {
                return local
                    .strftime(&format.replace("%Y", &local.year().to_string()))
                    .to_string();
            }
            return local.strftime(format).to_string();
        }
        let year = local.year() + shift;
        local
            .strftime(format.replace("%Y", &format!("{year:04}")).as_str())
            .to_string()
    }
}

fn parse_2(bytes: &[u8]) -> Option<i8> {
    let a = bytes[0].wrapping_sub(b'0');
    let b = bytes[1].wrapping_sub(b'0');
    (a <= 9 && b <= 9).then(|| i8::try_from(a * 10 + b).unwrap())
}

fn parse_4(bytes: &[u8]) -> Option<i16> {
    let a = u16::from(bytes[0].wrapping_sub(b'0'));
    let b = u16::from(bytes[1].wrapping_sub(b'0'));
    let c = u16::from(bytes[2].wrapping_sub(b'0'));
    let d = u16::from(bytes[3].wrapping_sub(b'0'));
    (a <= 9 && b <= 9 && c <= 9 && d <= 9)
        .then(|| i16::try_from(a * 1000 + b * 100 + c * 10 + d).unwrap())
}

fn fast_iso(value: &str) -> Option<Timestamp> {
    let bytes = value.as_bytes();
    if bytes.len() < 20
        || bytes[4] != b'-'
        || bytes[7] != b'-'
        || !matches!(bytes[10], b'T' | b't' | b' ')
        || bytes[13] != b':'
        || bytes[16] != b':'
    {
        return None;
    }
    let year = parse_4(&bytes[0..4])?;
    if year < 1 {
        return None;
    }
    let month = parse_2(&bytes[5..7])?;
    let day = parse_2(&bytes[8..10])?;
    let hour = parse_2(&bytes[11..13])?;
    let minute = parse_2(&bytes[14..16])?;
    let second = parse_2(&bytes[17..19])?;
    let mut i = 19;
    let mut micros: i32 = 0;
    if bytes.get(i) == Some(&b'.') {
        i += 1;
        let start = i;
        let mut scale = 100_000;
        while i < bytes.len() && bytes[i].is_ascii_digit() {
            if scale > 0 {
                micros += i32::from(bytes[i] - b'0') * scale;
                scale /= 10;
            }
            i += 1;
        }
        if i == start {
            return None;
        }
    }
    let offset_secs: i64 = match bytes.get(i).copied() {
        Some(b'Z' | b'z') if i + 1 == bytes.len() => 0,
        Some(sign @ (b'+' | b'-'))
            if i + 6 == bytes.len() && bytes[i + 3] == b':' =>
        {
            let oh = i64::from(parse_2(&bytes[i + 1..i + 3])?);
            let om = i64::from(parse_2(&bytes[i + 4..i + 6])?);
            if oh > 23 || om > 59 {
                return None;
            }
            let secs = oh * 3600 + om * 60;
            if sign == b'-' { -secs } else { secs }
        }
        _ => return None,
    };
    let date = jiff::civil::Date::new(year, month, day).ok()?;
    let time =
        jiff::civil::Time::new(hour, minute, second, micros * 1_000).ok()?;
    let local = date.to_datetime(time);
    let utc = if offset_secs == 0 {
        local
    } else {
        local
            .checked_sub(SignedDuration::from_secs(offset_secs))
            .ok()?
    };
    Timestamp::checked(utc).ok()
}

impl FromStr for Timestamp {
    type Err = crate::Error;

    fn from_str(value: &str) -> crate::Result<Self> {
        if let Some(parsed) = fast_iso(value) {
            return Ok(parsed);
        }
        let pieces =
            jiff::fmt::temporal::DateTimeParser::new().parse_pieces(value)?;
        let local = pieces
            .date()
            .to_datetime(pieces.time().unwrap_or(jiff::civil::Time::MIN));
        if local.year() < 1 {
            return Err("date value out of range".into());
        }
        let offset = pieces
            .to_numeric_offset()
            .map_or(0, jiff::tz::Offset::seconds);
        let utc =
            local.checked_sub(SignedDuration::from_secs(i64::from(offset)))?;
        let utc = utc
            .with()
            .subsec_nanosecond(utc.subsec_nanosecond() / 1_000 * 1_000)
            .build()?;
        Self::checked(utc)
    }
}

impl TryFrom<SystemTime> for Timestamp {
    type Error = crate::Error;

    fn try_from(value: SystemTime) -> crate::Result<Self> {
        let nanos = match value.duration_since(SystemTime::UNIX_EPOCH) {
            Ok(value) => i128::try_from(value.as_nanos())
                .expect("Duration nanoseconds fit in i128"),
            Err(error) => {
                -(i128::try_from(error.duration().as_nanos())
                    .expect("Duration nanoseconds fit in i128"))
            }
        };
        Self::from_nanosecond(nanos)
    }
}
