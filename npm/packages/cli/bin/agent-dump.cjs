#!/usr/bin/env node

const { runCli } = require("../lib/run-agent-dump.cjs");

runCli().catch((error) => {
  process.stderr.write(`Failed to start agent-dump CLI: ${error.message}\n`);
  process.exitCode = 1;
});
