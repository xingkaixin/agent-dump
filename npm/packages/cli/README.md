# @agent-dump/cli

Native `agent-dump` binaries for `bunx` and `npx`.

The package downloads the matching native binary for the current platform during installation
and verifies it against the published checksum manifest before exposing `agent-dump`.

```bash
bunx @agent-dump/cli --help
npx @agent-dump/cli --help
```

Supported targets:

- `darwin-x64`
- `darwin-arm64`
- `linux-x64`
- `win32-x64`

The Python CLI remains the source of truth in the main repository:
[xingkaixin/agent-dump](https://github.com/xingkaixin/agent-dump).
