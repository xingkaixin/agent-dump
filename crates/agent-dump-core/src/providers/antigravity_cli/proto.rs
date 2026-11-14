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
    pub view_file: Option<FileView>,
    pub user: Option<UserPrompt>,
    pub assistant: Option<Text>,
    pub run_command: Option<CommandRun>,
    pub title: Option<Title>,
    pub error: Option<ErrorDetails>,
    pub mcp: Option<McpCall>,
    pub tool: Option<ToolExecution>,
}

impl Message for Step {
    fn field(&mut self, number: u32, field: Field<'_>) -> crate::Result<()> {
        match number {
            5 => merge(&mut self.metadata, field),
            14 => merge(&mut self.view_file, field),
            19 => merge(&mut self.user, field),
            20 => merge(&mut self.assistant, field),
            28 => merge(&mut self.run_command, field),
            30 => merge(&mut self.title, field),
            31 => merge(&mut self.error, field),
            47 => merge(&mut self.mcp, field),
            140 => merge(&mut self.tool, field),
            _ => Ok(()),
        }
    }
}

#[derive(Default)]
pub struct ToolExecution {
    pub result: Option<Text>,
}

impl Message for ToolExecution {
    fn field(&mut self, number: u32, field: Field<'_>) -> crate::Result<()> {
        if number == 2 {
            merge(&mut self.result, field)?;
        }
        Ok(())
    }
}

#[derive(Default)]
pub struct FileView {
    pub content: Option<String>,
}

impl Message for FileView {
    fn field(&mut self, number: u32, field: Field<'_>) -> crate::Result<()> {
        if number == 4 {
            self.content = Some(field.string()?);
        }
        Ok(())
    }
}

#[derive(Default)]
pub struct CommandRun {
    pub output: Option<Text>,
}

impl Message for CommandRun {
    fn field(&mut self, number: u32, field: Field<'_>) -> crate::Result<()> {
        if number == 21 {
            merge(&mut self.output, field)?;
        }
        Ok(())
    }
}

#[derive(Default)]
pub struct McpCall {
    pub result: Option<String>,
}

impl Message for McpCall {
    fn field(&mut self, number: u32, field: Field<'_>) -> crate::Result<()> {
        if number == 3 {
            self.result = Some(field.string()?);
        }
        Ok(())
    }
}

#[derive(Default)]
pub struct ErrorDetails {
    pub message: Option<String>,
    pub details: Option<String>,
}

impl Message for ErrorDetails {
    fn field(&mut self, number: u32, field: Field<'_>) -> crate::Result<()> {
        match number {
            2 => self.message = Some(field.string()?),
            3 => self.details = Some(field.string()?),
            _ => {}
        }
        Ok(())
    }
}

#[derive(Default)]
pub struct UserPrompt {
    pub text: Option<String>,
    pub items: Vec<UserItem>,
}

impl Message for UserPrompt {
    fn field(&mut self, number: u32, field: Field<'_>) -> crate::Result<()> {
        match number {
            2 => self.text = Some(field.string()?),
            3 => self.items.push(UserItem::decode(field.bytes()?)?),
            _ => {}
        }
        Ok(())
    }
}

#[derive(Default)]
pub struct UserItem {
    pub text: Option<String>,
    pub context: Option<UserContext>,
}

impl Message for UserItem {
    fn field(&mut self, number: u32, field: Field<'_>) -> crate::Result<()> {
        match number {
            1 => self.text = Some(field.string()?),
            2 => merge(&mut self.context, field)?,
            _ => {}
        }
        Ok(())
    }
}

#[derive(Default)]
pub struct UserContext {
    pub file: Option<ContextTarget>,
    pub directory: Option<ContextTarget>,
}

impl Message for UserContext {
    fn field(&mut self, number: u32, field: Field<'_>) -> crate::Result<()> {
        match number {
            1 => merge(&mut self.file, field)?,
            2 => merge(&mut self.directory, field)?,
            _ => {}
        }
        Ok(())
    }
}

#[derive(Default)]
pub struct ContextTarget {
    pub uri: Option<String>,
}

impl Message for ContextTarget {
    fn field(&mut self, number: u32, field: Field<'_>) -> crate::Result<()> {
        if number == 5 {
            self.uri = Some(field.string()?);
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
    pub model: Option<Model>,
    pub retries: Vec<Retry>,
}

impl Message for Metadata {
    fn field(&mut self, number: u32, field: Field<'_>) -> crate::Result<()> {
        match number {
            1 => merge(&mut self.created, field),
            4 => merge(&mut self.call, field),
            9 => merge(&mut self.usage, field),
            24 => merge(&mut self.model, field),
            28 => {
                self.retries.push(Retry::decode(field.bytes()?)?);
                Ok(())
            }
            _ => Ok(()),
        }
    }
}

#[derive(Default)]
pub struct Model {
    pub name: Option<String>,
    pub api_name: Option<String>,
}

impl Message for Model {
    fn field(&mut self, number: u32, field: Field<'_>) -> crate::Result<()> {
        match number {
            8 => self.name = Some(field.string()?),
            12 => self.api_name = Some(field.string()?),
            _ => {}
        }
        Ok(())
    }
}

#[derive(Default)]
pub struct TrajectoryMetadata {
    pub workspaces: Vec<String>,
}

impl Message for TrajectoryMetadata {
    fn field(&mut self, number: u32, field: Field<'_>) -> crate::Result<()> {
        if number == 7 {
            self.workspaces.push(field.string()?);
        }
        Ok(())
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
