use crate::compat::value::integer;
use serde_json::Value;

#[derive(Clone, Copy, Default)]
pub struct Totals {
    pub input: i64,
    pub output: i64,
    pub cache_read: i64,
}

impl std::ops::AddAssign for Totals {
    fn add_assign(&mut self, other: Self) {
        self.input += other.input;
        self.output += other.output;
        self.cache_read += other.cache_read;
    }
}

#[derive(Default)]
pub struct Usage {
    previous_total: i64,
    previous: [i64; 4],
    totals: Totals,
    replaying: Option<u128>,
    latest_record: Option<(String, [i64; 4])>,
}

fn uuid_v7(value: &Value) -> Option<u128> {
    let hex = value.as_str()?.replace('-', "");
    let id = (hex.len() == 32)
        .then(|| u128::from_str_radix(&hex, 16).ok())
        .flatten()?;
    (((id >> 76) & 0xf) == 7).then_some(id)
}

fn counts(value: &Value) -> [i64; 4] {
    [
        integer(&value["input_tokens"]),
        integer(&value["output_tokens"]),
        integer(&value["reasoning_output_tokens"]),
        integer(
            value
                .get("cached_input_tokens")
                .unwrap_or_else(|| &value["cache_read_input_tokens"]),
        ),
    ]
}

impl Usage {
    /// A forked rollout opens with its parent's history, which the parent
    /// already counts.
    pub fn new(meta: &Value) -> Self {
        let forked = meta["forked_from_id"]
            .as_str()
            .is_some_and(|id| !id.is_empty());
        Self {
            replaying: uuid_v7(&meta["id"]).filter(|_| forked),
            ..Self::default()
        }
    }

    pub const fn totals(&self) -> Totals {
        self.totals
    }

    // UUIDv7 ids order by creation time; replayed turns started before the
    // fork did.
    pub fn turn(&mut self, payload: &Value) {
        if let Some(session) = self.replaying
            && uuid_v7(&payload["turn_id"]).is_none_or(|turn| turn >= session)
        {
            self.replaying = None;
        }
    }

    pub fn consume(&mut self, payload: &Value) {
        let total = &payload["info"]["total_token_usage"];
        let last = &payload["info"]["last_token_usage"];
        let cumulative = integer(&total["total_tokens"]);
        if cumulative > 0 && cumulative == self.previous_total {
            return;
        }
        let delta = if last.is_object() {
            counts(last)
        } else if total.is_object() && cumulative > 0 {
            let next = counts(total);
            std::array::from_fn(|index| next[index] - self.previous[index])
        } else {
            return;
        };
        if total.is_object() {
            self.previous = counts(total);
        }
        if cumulative > 0 {
            self.previous_total = cumulative;
        }
        if self.replaying.is_some() {
            return;
        }
        if delta.iter().any(|count| *count > 0) {
            self.latest_record = None;
        }
        self.add(delta);
    }

    pub fn record(&mut self, payload: &Value) {
        if self.replaying.is_none() {
            self.latest_record = payload["response_id"]
                .as_str()
                .map(|id| (id.to_owned(), counts(&payload["usage"])));
        }
    }

    // Remote compaction reports its usage only in a token_usage_record.
    // Local compaction advances token_count between that record and the
    // compacted marker.
    pub fn compacted(&mut self, payload: &Value) {
        if let Some((id, delta)) = self.latest_record.take()
            && payload["compaction_response_id"] == id.as_str()
        {
            self.add(delta);
        }
    }

    fn add(&mut self, delta: [i64; 4]) {
        let [input, output, reasoning, cache_read] =
            delta.map(|count| count.max(0));
        self.totals += Totals {
            input,
            output: (output - reasoning).max(0) + reasoning,
            cache_read,
        };
    }
}
