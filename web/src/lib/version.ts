// Injected at build time from Cargo.toml (see astro.config.mjs).
declare const __AGENT_DUMP_VERSION__: string;

export const version: string = __AGENT_DUMP_VERSION__;
