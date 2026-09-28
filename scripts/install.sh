#!/bin/sh
set -eu

fail() { printf 'agent-dump: %s\n' "$*" >&2; exit 1; }

install_agent_dump() {
  version=${AGENT_DUMP_VERSION:-}
  install_dir=${AGENT_DUMP_INSTALL_DIR:-"$HOME/.local/bin"}
  releases=https://github.com/xingkaixin/agent-dump/releases
  case "$install_dir" in /*) ;; *) fail 'AGENT_DUMP_INSTALL_DIR must be an absolute path.' ;; esac
  case "$(uname -s)/$(uname -m)" in
    Darwin/arm64|Darwin/aarch64) target=darwin-arm64 ;;
    Darwin/x86_64) target=darwin-x64 ;;
    Linux/x86_64)
      target=linux-x64
      libc=$(getconf GNU_LIBC_VERSION 2>/dev/null) || fail 'Linux requires glibc 2.17 or later; musl is not supported.'
      printf '%s\n' "$libc" | awk '$1 == "glibc" { split($2, v, "."); if (v[1] > 2 || (v[1] == 2 && v[2] >= 17)) ok = 1 } END { exit !ok }' || fail 'Linux requires glibc 2.17 or later.'
      ;;
    *) fail 'Supported platforms: macOS arm64/x64 and Linux x64 (glibc 2.17+).' ;;
  esac
  for tool in curl mktemp; do command -v "$tool" >/dev/null 2>&1 || fail "Missing required command: $tool"; done
  if command -v sha256sum >/dev/null 2>&1; then
    hash_tool=sha256sum
  elif command -v shasum >/dev/null 2>&1; then
    hash_tool=shasum
  else
    fail 'SHA-256 verification requires sha256sum or shasum.'
  fi
  if [ -z "$version" ]; then
    latest=$(curl -fsSL --proto '=https' --tlsv1.2 -o /dev/null -w '%{url_effective}' "$releases/latest")
    version=${latest##*/}
  fi
  version=${version#v}
  printf '%s\n' "$version" | LC_ALL=C grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || fail 'Expected a stable version such as 1.0.0.'
  destination=$install_dir/agent-dump
  [ ! -L "$destination" ] || fail "Refusing to replace a symlink: $destination. Update through its original package manager."
  [ ! -d "$destination" ] || fail "Destination is a directory: $destination"
  if [ -x "$destination" ] && [ "$("$destination" --version 2>/dev/null || true)" = "agent-dump $version" ]; then
    printf 'agent-dump %s is already installed at %s\n' "$version" "$destination"
    return
  fi
  temp_dir=$(mktemp -d)
  staged=
  trap 'rm -rf "$temp_dir"; if [ -n "$staged" ]; then rm -f "$staged"; fi' 0
  trap 'exit 1' HUP INT TERM
  asset=agent-dump-$target
  base=$releases/download/v$version
  printf 'Downloading agent-dump %s (%s)…\n' "$version" "$target"
  curl -fsSL --proto '=https' --tlsv1.2 "$base/SHA256SUMS" -o "$temp_dir/SHA256SUMS"
  expected=$(awk -v name="$asset" '$2 == name { print $1 }' "$temp_dir/SHA256SUMS")
  [ "${#expected}" -eq 64 ] || fail "Missing or invalid checksum for $asset"
  case "$expected" in *[!a-f0-9]*) fail 'Invalid SHA-256 checksum.' ;; esac
  curl -fsSL --proto '=https' --tlsv1.2 "$base/$asset" -o "$temp_dir/$asset"
  if [ "$hash_tool" = sha256sum ]; then
    actual=$(sha256sum "$temp_dir/$asset" | awk '{print $1}')
  else
    actual=$(shasum -a 256 "$temp_dir/$asset" | awk '{print $1}')
  fi
  [ "$actual" = "$expected" ] || fail 'Checksum mismatch; existing installation was not changed.'
  mv "$temp_dir/$asset" "$temp_dir/agent-dump"
  chmod 755 "$temp_dir/agent-dump"
  [ "$("$temp_dir/agent-dump" --version)" = "agent-dump $version" ] || fail 'Downloaded executable failed its version check.'
  mkdir -p "$install_dir"
  staged=$(mktemp "$install_dir/.agent-dump.XXXXXX")
  cp "$temp_dir/agent-dump" "$staged"
  chmod 755 "$staged"
  mv -f "$staged" "$destination"
  staged=
  printf 'Installed agent-dump %s at %s\n' "$version" "$destination"
  case ":$PATH:" in
    *":$install_dir:"*) ;;
    *) printf 'Add %s to PATH in your shell configuration.\n' "$install_dir" ;;
  esac
  current=$(command -v agent-dump || true)
  if [ -n "$current" ] && [ "$current" != "$destination" ]; then
    printf 'Your PATH currently selects %s. Adjust PATH to use %s.\n' "$current" "$destination"
  fi
  printf 'Run agent-dump --help to get started. Run this installer again to update.\n'
}

install_agent_dump
