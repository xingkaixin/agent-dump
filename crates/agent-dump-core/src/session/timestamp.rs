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
        Self(jiff::Timestamp::now().to_zoned(TimeZone::UTC).datetime())
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
        format!(
            "{}.{:06}+00:00",
            self.0.strftime("%Y-%m-%dT%H:%M:%S"),
            self.0.subsec_nanosecond() / 1_000
        )
    }
    pub fn local_date(self) -> jiff::civil::Date {
        let text = self.format_local("%Y-%m-%d");
        let parts: Vec<_> = text.split('-').collect();
        jiff::civil::Date::new(
            parts[0].parse().unwrap(),
            parts[1].parse().unwrap(),
            parts[2].parse().unwrap(),
        )
        .unwrap()
    }
    pub fn iso_local(self) -> String {
        let mut result =
            format!("{}T{}", self.local_date(), self.format_local("%H:%M:%S"));
        let micros = self.0.subsec_nanosecond() / 1_000;
        if micros != 0 {
            write!(result, ".{micros:06}").unwrap();
        }
        result + &self.format_local("%:z")
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
        let zone = TimeZone::system();
        if let Ok(timestamp) =
            jiff::Timestamp::from_microsecond(self.as_microsecond())
        {
            let local = timestamp.to_zoned(zone);
            // CPython delegates %Y padding to libc; glibc does not pad small years.
            if cfg!(all(target_os = "linux", target_env = "gnu")) {
                return local
                    .strftime(&format.replace("%Y", &local.year().to_string()))
                    .to_string();
            }
            return local.strftime(format).to_string();
        }
        // Jiff reserves 26 hours at each timestamp boundary for zone conversion.
        // Far-future IANA rules repeat with the 400-year Gregorian calendar cycle.
        let shifted = self.0.with().year(self.0.year() - 400).build().unwrap();
        let local = shifted
            .to_zoned(TimeZone::UTC)
            .unwrap()
            .with_time_zone(zone);
        let year = local.year() + 400;
        local
            .strftime(format.replace("%Y", &format!("{year:04}")).as_str())
            .to_string()
    }
}

impl FromStr for Timestamp {
    type Err = crate::Error;

    fn from_str(value: &str) -> crate::Result<Self> {
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
