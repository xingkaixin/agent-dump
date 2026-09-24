use jiff::{SignedDuration, civil::DateTime, tz::TimeZone};
use std::str::FromStr;
use std::time::SystemTime;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct Timestamp(DateTime);

impl Timestamp {
    pub const UNIX_EPOCH: Self = Self(jiff::civil::date(1970, 1, 1).at(0, 0, 0, 0));

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
            return Err("date value out of range".into());
        }
        Ok(Self(value))
    }

    pub fn checked_sub(self, duration: SignedDuration) -> crate::Result<Self> {
        Self::checked(self.0.checked_sub(duration)?)
    }

    pub fn as_microsecond(self) -> i64 {
        self.0.duration_since(Self::UNIX_EPOCH.0).as_micros() as i64
    }

    pub fn iso_utc(self) -> String {
        format!(
            "{}.{:06}+00:00",
            self.0.strftime("%Y-%m-%dT%H:%M:%S"),
            self.0.subsec_nanosecond() / 1_000
        )
    }

    pub fn as_millisecond(self) -> i64 {
        // Python exports int(datetime.timestamp() * 1000), including float rounding.
        (self.as_microsecond() as f64 / 1_000_000.0 * 1_000.0) as i64
    }

    pub fn format_local(self, format: &str) -> String {
        let zone = TimeZone::system();
        if let Ok(timestamp) = jiff::Timestamp::from_microsecond(self.as_microsecond()) {
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
        let pieces = jiff::fmt::temporal::DateTimeParser::new().parse_pieces(value)?;
        let local = pieces
            .date()
            .to_datetime(pieces.time().unwrap_or(jiff::civil::Time::MIN));
        if local.year() < 1 {
            return Err("date value out of range".into());
        }
        let offset = pieces
            .to_numeric_offset()
            .map_or(0, |offset| offset.seconds());
        let utc = local.checked_sub(SignedDuration::from_secs(i64::from(offset)))?;
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
            Ok(value) => value.as_nanos() as i128,
            Err(error) => -(error.duration().as_nanos() as i128),
        };
        Self::from_nanosecond(nanos)
    }
}
