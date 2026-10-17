pub enum Field<'a> {
    Varint(u64),
    Bytes(&'a [u8]),
    Fixed,
}

impl<'a> Field<'a> {
    fn varint(self) -> crate::Result<u64> {
        match self {
            Self::Varint(value) => Ok(value),
            _ => Err("protobuf field is not a varint".into()),
        }
    }

    fn bytes(self) -> crate::Result<&'a [u8]> {
        match self {
            Self::Bytes(bytes) => Ok(bytes),
            _ => Err("protobuf field is not length-delimited".into()),
        }
    }

    fn string(self) -> crate::Result<String> {
        Ok(std::str::from_utf8(self.bytes()?)?.to_owned())
    }
}

fn varint(bytes: &mut &[u8]) -> crate::Result<u64> {
    let mut value = 0;
    for (index, &byte) in bytes.iter().enumerate().take(10) {
        if index == 9 && byte > 1 {
            return Err("protobuf varint overflows 64 bits".into());
        }
        value |= u64::from(byte & 0x7f) << (7 * index);
        if byte & 0x80 == 0 {
            *bytes = &bytes[index + 1..];
            return Ok(value);
        }
    }
    Err("truncated protobuf varint".into())
}

fn take<'a>(bytes: &mut &'a [u8], length: u64) -> crate::Result<&'a [u8]> {
    let length = usize::try_from(length)
        .ok()
        .filter(|&length| length <= bytes.len())
        .ok_or("truncated protobuf field")?;
    let (value, rest) = bytes.split_at(length);
    *bytes = rest;
    Ok(value)
}

pub fn fields<'a>(
    mut bytes: &'a [u8],
    mut visit: impl FnMut(u32, Field<'a>) -> crate::Result<()>,
) -> crate::Result<()> {
    while !bytes.is_empty() {
        let key = u32::try_from(varint(&mut bytes)?)
            .map_err(|_| "invalid protobuf key")?;
        if key >> 3 == 0 {
            return Err("invalid protobuf field number 0".into());
        }
        let field = match key & 7 {
            0 => Field::Varint(varint(&mut bytes)?),
            1 => {
                take(&mut bytes, 8)?;
                Field::Fixed
            }
            2 => {
                let length = varint(&mut bytes)?;
                Field::Bytes(take(&mut bytes, length)?)
            }
            5 => {
                take(&mut bytes, 4)?;
                Field::Fixed
            }
            kind => {
                return Err(
                    format!("unsupported protobuf wire type {kind}").into()
                );
            }
        };
        visit(key >> 3, field)?;
    }
    Ok(())
}

pub trait Message: Default {
    fn field(&mut self, number: u32, field: Field<'_>) -> crate::Result<()>;

    fn decode(bytes: &[u8]) -> crate::Result<Self> {
        let mut message = Self::default();
        message.merge(bytes)?;
        Ok(message)
    }

    fn merge(&mut self, bytes: &[u8]) -> crate::Result<()> {
        fields(bytes, |number, field| self.field(number, field))
    }
}

// A repeated singular message field merges into one value, as in protobuf.
fn merge<T: Message>(
    slot: &mut Option<T>,
    field: Field<'_>,
) -> crate::Result<()> {
    slot.get_or_insert_default().merge(field.bytes()?)
}

#[derive(Default)]
pub struct Step {
    pub metadata: Option<Metadata>,
    pub user: Option<UserPrompt>,
    pub assistant: Option<Text>,
    pub title: Option<Title>,
}

impl Message for Step {
    fn field(&mut self, number: u32, field: Field<'_>) -> crate::Result<()> {
        match number {
            5 => merge(&mut self.metadata, field),
            19 => merge(&mut self.user, field),
            20 => merge(&mut self.assistant, field),
            30 => merge(&mut self.title, field),
            _ => Ok(()),
        }
    }
}

#[derive(Default)]
pub struct UserPrompt {
    pub text: Option<String>,
    pub content: Option<Text>,
}

impl Message for UserPrompt {
    fn field(&mut self, number: u32, field: Field<'_>) -> crate::Result<()> {
        match number {
            2 => self.text = Some(field.string()?),
            3 => merge(&mut self.content, field)?,
            _ => {}
        }
        Ok(())
    }
}

#[derive(Default)]
pub struct Text {
    pub text: Option<String>,
}

impl Message for Text {
    fn field(&mut self, number: u32, field: Field<'_>) -> crate::Result<()> {
        if number == 1 {
            self.text = Some(field.string()?);
        }
        Ok(())
    }
}

#[derive(Default)]
pub struct Title {
    pub text: Option<String>,
}

impl Message for Title {
    fn field(&mut self, number: u32, field: Field<'_>) -> crate::Result<()> {
        if number == 4 {
            self.text = Some(field.string()?);
        }
        Ok(())
    }
}

#[derive(Default)]
pub struct Metadata {
    pub created: Option<Time>,
    pub call: Option<ToolCall>,
    pub usage: Option<Usage>,
    pub retries: Vec<Retry>,
}

impl Message for Metadata {
    fn field(&mut self, number: u32, field: Field<'_>) -> crate::Result<()> {
        match number {
            1 => merge(&mut self.created, field),
            4 => merge(&mut self.call, field),
            9 => merge(&mut self.usage, field),
            28 => {
                self.retries.push(Retry::decode(field.bytes()?)?);
                Ok(())
            }
            _ => Ok(()),
        }
    }
}

#[derive(Default)]
pub struct Time {
    pub seconds: i64,
    pub nanos: i64,
}

impl Message for Time {
    fn field(&mut self, number: u32, field: Field<'_>) -> crate::Result<()> {
        match number {
            1 => self.seconds = field.varint()?.cast_signed(),
            2 => self.nanos = field.varint()?.cast_signed(),
            _ => {}
        }
        Ok(())
    }
}

#[derive(Default)]
pub struct ToolCall {
    pub id: Option<String>,
    pub name: Option<String>,
    pub input: Option<String>,
    pub secondary_name: Option<String>,
}

impl Message for ToolCall {
    fn field(&mut self, number: u32, field: Field<'_>) -> crate::Result<()> {
        match number {
            1 => self.id = Some(field.string()?),
            2 => self.name = Some(field.string()?),
            3 => self.input = Some(field.string()?),
            9 => self.secondary_name = Some(field.string()?),
            _ => {}
        }
        Ok(())
    }
}

#[derive(Default)]
pub struct Retry {
    pub usage: Option<Usage>,
}

impl Message for Retry {
    fn field(&mut self, number: u32, field: Field<'_>) -> crate::Result<()> {
        if number == 2 {
            merge(&mut self.usage, field)?;
        }
        Ok(())
    }
}

#[derive(Default)]
pub struct Usage {
    pub model_id: Option<u64>,
    pub input: u64,
    pub total_output: u64,
    pub cache_create: u64,
    pub cache_read: u64,
    pub message_id: Option<String>,
    pub reasoning: u64,
    pub visible_output: u64,
    pub response_id: Option<String>,
    pub provider_message_id: Option<String>,
}

impl Message for Usage {
    fn field(&mut self, number: u32, field: Field<'_>) -> crate::Result<()> {
        match number {
            1 => self.model_id = Some(field.varint()?),
            2 => self.input = field.varint()?,
            3 => self.total_output = field.varint()?,
            4 => self.cache_create = field.varint()?,
            5 => self.cache_read = field.varint()?,
            7 => self.message_id = Some(field.string()?),
            9 => self.reasoning = field.varint()?,
            10 => self.visible_output = field.varint()?,
            11 => self.response_id = Some(field.string()?),
            12 => self.provider_message_id = Some(field.string()?),
            _ => {}
        }
        Ok(())
    }
}

#[derive(Default)]
pub struct Generation {
    pub chat: Option<ChatGeneration>,
}

impl Message for Generation {
    fn field(&mut self, number: u32, field: Field<'_>) -> crate::Result<()> {
        if number == 1 {
            merge(&mut self.chat, field)?;
        }
        Ok(())
    }
}

#[derive(Default)]
pub struct ChatGeneration {
    pub model_id: Option<u64>,
    pub model: Option<String>,
}

impl Message for ChatGeneration {
    fn field(&mut self, number: u32, field: Field<'_>) -> crate::Result<()> {
        match number {
            3 => self.model_id = Some(field.varint()?),
            19 => self.model = Some(field.string()?),
            _ => {}
        }
        Ok(())
    }
}

#[cfg(test)]
pub mod tests {
    use super::*;

    pub fn varint(number: u32, value: u64) -> Vec<u8> {
        let mut bytes = encode(u64::from(number) << 3);
        bytes.extend(encode(value));
        bytes
    }

    pub fn bytes(number: u32, value: impl AsRef<[u8]>) -> Vec<u8> {
        let value = value.as_ref();
        let mut bytes = encode(u64::from(number) << 3 | 2);
        bytes.extend(encode(u64::try_from(value.len()).unwrap()));
        bytes.extend(value);
        bytes
    }

    fn encode(mut value: u64) -> Vec<u8> {
        let mut bytes = Vec::new();
        while value >= 0x80 {
            bytes.push(u8::try_from(value & 0x7f).unwrap() | 0x80);
            value >>= 7;
        }
        bytes.push(u8::try_from(value).unwrap());
        bytes
    }

    fn step() -> Vec<u8> {
        [
            varint(100, u64::MAX),
            vec![0x09, 1, 2, 3, 4, 5, 6, 7, 8, 0x0d, 1, 2, 3, 4],
            bytes(99, [0xff, 0xfe]),
            bytes(
                5,
                bytes(1, [varint(1, 1_788_000_000), varint(2, 5)].concat()),
            ),
            bytes(5, bytes(4, [bytes(1, "call"), bytes(2, "read")].concat())),
            bytes(
                5,
                bytes(
                    9,
                    [varint(1, 7), varint(2, 10), bytes(11, "response")]
                        .concat(),
                ),
            ),
            bytes(5, bytes(28, bytes(2, varint(9, 3)))),
            bytes(5, bytes(28, Vec::new())),
            bytes(19, [bytes(2, "Hi"), bytes(3, bytes(1, "Nested"))].concat()),
            bytes(20, bytes(1, "Done")),
            bytes(30, bytes(4, "Title")),
        ]
        .concat()
    }

    #[test]
    fn decodes_known_fields_merges_messages_and_skips_unknown_fields() {
        let step = Step::decode(&step()).unwrap();
        let metadata = step.metadata.unwrap();
        let created = metadata.created.unwrap();
        assert_eq!((created.seconds, created.nanos), (1_788_000_000, 5));
        let call = metadata.call.unwrap();
        assert_eq!(call.id.as_deref(), Some("call"));
        assert_eq!(call.name.as_deref(), Some("read"));
        let usage = metadata.usage.unwrap();
        assert_eq!(usage.model_id, Some(7));
        assert_eq!(usage.input, 10);
        assert_eq!(usage.response_id.as_deref(), Some("response"));
        assert_eq!(metadata.retries.len(), 2);
        assert_eq!(metadata.retries[0].usage.as_ref().unwrap().reasoning, 3);
        assert!(metadata.retries[1].usage.is_none());
        let user = step.user.unwrap();
        assert_eq!(user.text.as_deref(), Some("Hi"));
        assert_eq!(user.content.unwrap().text.as_deref(), Some("Nested"));
        assert_eq!(step.assistant.unwrap().text.as_deref(), Some("Done"));
        assert_eq!(step.title.unwrap().text.as_deref(), Some("Title"));
        let generation = Generation::decode(&bytes(
            1,
            [varint(3, 7), bytes(19, "gemini-2.5-flash")].concat(),
        ))
        .unwrap()
        .chat
        .unwrap();
        assert_eq!(generation.model_id, Some(7));
        assert_eq!(generation.model.as_deref(), Some("gemini-2.5-flash"));
    }

    #[test]
    fn truncated_and_malformed_input_is_an_error() {
        let valid = step();
        for end in 0..valid.len() {
            let _ = Step::decode(&valid[..end]);
        }
        for (bytes, message) in [
            (vec![0x08], "truncated protobuf varint"),
            (vec![0x08, 0x80], "truncated protobuf varint"),
            (
                vec![
                    0x08, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80,
                    0x02,
                ],
                "protobuf varint overflows 64 bits",
            ),
            (
                vec![
                    0x08, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80,
                    0x80, 0x00,
                ],
                "protobuf varint overflows 64 bits",
            ),
            (vec![0xa2, 0x01, 0x05, 0x0a], "truncated protobuf field"),
            (vec![0xa2, 0x01, 0xff], "truncated protobuf varint"),
            (vec![0x09, 1, 2, 3], "truncated protobuf field"),
            (vec![0x0d, 1, 2], "truncated protobuf field"),
            (vec![0x02, 0x00], "invalid protobuf field number 0"),
            (vec![0x80, 0x80, 0x80, 0x80, 0x10], "invalid protobuf key"),
            (vec![0x0b], "unsupported protobuf wire type 3"),
            (vec![0x0c], "unsupported protobuf wire type 4"),
            (vec![0x0e], "unsupported protobuf wire type 6"),
            (vec![0x0f], "unsupported protobuf wire type 7"),
            (
                vec![0xa0, 0x01, 0x01],
                "protobuf field is not length-delimited",
            ),
            (
                bytes(5, bytes(1, bytes(1, "x"))),
                "protobuf field is not a varint",
            ),
        ] {
            let error = Step::decode(&bytes).err().unwrap();
            assert_eq!(error.to_string(), message, "{bytes:02x?}");
        }
        assert!(Step::decode(&bytes(20, bytes(1, [0xff]))).is_err());
        assert_eq!(
            varint(1, u64::MAX)[1..],
            [0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x01]
        );
        let mut maximum = &varint(1, u64::MAX)[1..];
        assert_eq!(super::varint(&mut maximum).unwrap(), u64::MAX);
    }
}
