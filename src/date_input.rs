use agent_dump_core::compat::value::decimal_digit;
use agent_dump_core::output::i18n::t;
use jiff::civil::Date;

pub fn parse(raw: &str) -> Option<Date> {
    use std::sync::LazyLock;
    static SEPARATED: LazyLock<regex::Regex> = LazyLock::new(|| {
        regex::Regex::new(r"^(\p{Nd}{4})-(1[0-2]|0[1-9]|[1-9])-(3[0-1]|[0-2]\p{Nd}|\p{Nd}| [1-9])$")
            .unwrap()
    });
    static COMPACT: LazyLock<regex::Regex> = LazyLock::new(|| {
        regex::Regex::new(r"^(\p{Nd}{4})(1[0-2]|0[1-9]|[1-9])(3[0-1]|[0-2]\p{Nd}|\p{Nd}| [1-9])$")
            .unwrap()
    });
    let raw = raw.trim();
    let parts = SEPARATED.captures(raw).or_else(|| COMPACT.captures(raw))?;
    let number = |index| {
        parts
            .get(index)
            .unwrap()
            .as_str()
            .trim()
            .chars()
            .map(decimal_digit)
            .collect::<String>()
    };
    let date = Date::new(
        number(1).parse().ok()?,
        number(2).parse().ok()?,
        number(3).parse().ok()?,
    )
    .ok()?;
    (date.year() > 0).then_some(date)
}

pub fn optional_range(
    since: Option<&str>,
    until: Option<&str>,
    zh: bool,
) -> crate::Result<Option<(Date, Date)>> {
    let since = since.filter(|s| !s.is_empty());
    let until = until.filter(|s| !s.is_empty());
    if since.is_none() && until.is_none() {
        return Ok(None);
    }
    let today = jiff::ZonedDateTime::now().date();
    let parse_date = |raw| {
        parse(raw).ok_or_else(|| t("COLLECT_DATE_FORMAT_INVALID", zh, &[]))
    };
    let (start, end) = match (since, until) {
        (Some(s), None) => (parse_date(s)?, today),
        (Some(s), Some(u)) => (parse_date(s)?, parse_date(u)?),
        (None, Some(u)) => {
            let end = parse_date(u)?;
            (Date::new(end.year(), end.month(), 1)?, end)
        }
        (None, None) => unreachable!(),
    };
    if start > end {
        return Err(t("COLLECT_DATE_RANGE_INVALID", zh, &[]).into());
    }
    Ok(Some((start, end)))
}

pub fn collect_range(
    since: Option<&str>,
    until: Option<&str>,
    days: Option<i64>,
    zh: bool,
) -> crate::Result<(Date, Date)> {
    if let Some(range) = optional_range(since, until, zh)? {
        return Ok(range);
    }
    let today = jiff::ZonedDateTime::now().date();
    let start = today.checked_sub(jiff::Span::new().days(days.unwrap_or(0)))?;
    if start > today {
        return Err(t("COLLECT_DATE_RANGE_INVALID", zh, &[]).into());
    }
    Ok((start, today))
}
