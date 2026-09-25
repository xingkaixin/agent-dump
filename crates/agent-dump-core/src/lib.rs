pub mod compat;
pub mod config;
pub mod output;
pub mod providers;
pub mod query;
pub mod session;
pub mod storage;

pub type Error = Box<dyn std::error::Error + Send + Sync>;
pub type Result<T> = std::result::Result<T, Error>;
