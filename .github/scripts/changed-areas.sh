#!/usr/bin/env bash
# 从 stdin 读取变更文件（一行一个），输出 code=true|false 和 web=true|false。
# 未识别的路径一律算 code：漏跑检查的代价高于多跑一次。
set -euo pipefail

code=false
web=false

while IFS= read -r file; do
  case "$file" in
    web/README.md) ;;
    web/*) web=true ;;
    # 不写 *.md：resources/ 下的文件会嵌入二进制，npm/packages/ 下的会进 npm 包
    docs/* | skills/* | assets/* | LICENSE | .github/*.md | .github/dependabot.yml) ;;
    # astro.config.mjs 从 Cargo.toml 读版本
    Cargo.toml | .github/*)
      code=true
      web=true
      ;;
    */*) code=true ;;
    *.md) ;;
    *) code=true ;;
  esac
done

echo "code=$code"
echo "web=$web"
