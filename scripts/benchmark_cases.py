"""CLI workloads and independent checks; no imports from the implementation under test."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from benchmark_fixtures import Profile, codex_id, session_messages


@dataclass(frozen=True)
class Case:
    name: str
    args: tuple[str, ...]
    check: str
    provider: str | None = None
    index: str = "empty"
    stdin: str = ""


def cases(profile: Profile) -> list[Case]:
    large = f"codex://{codex_id(profile.sessions_per_provider)}"
    all_dates = ("-d", "36500")
    collect_dates = ("--since", "20260115", "--until", "20260116", "--save", "report.md")
    return [
        Case("startup-version", ("--version",), "version"),
        Case("startup-help", ("--help",), "help"),
        Case("list-jsonl", ("--list", "--no-metadata-summary", *all_dates, "-q", "provider:codex"), "list", "codex"),
        Case(
            "list-sqlite",
            ("--list", "--no-metadata-summary", *all_dates, "-q", "provider:opencode"),
            "list",
            "opencode",
        ),
        Case("list-all", ("--list", "--no-metadata-summary", *all_dates), "list"),
        Case("stats-all", ("--stats", *all_dates), "stats"),
        Case("head-large-jsonl", (large, "--head"), "head"),
        Case("print-large-jsonl", (large, "--format", "print"), "print"),
        Case("export-large-json-md", (large, "--format", "json,md", "--output", "exports"), "export-large"),
        Case(
            "export-batch-jsonl",
            ("--interactive", *all_dates, "-q", "provider:codex", "--format", "json", "--output", "exports"),
            "export-batch",
            "codex",
            stdin="all\n",
        ),
        Case("reindex-empty", ("--reindex", *all_dates), "reindex"),
        Case("search-cold-index", ("--search", "quartz", *all_dates), "search"),
        Case("search-warm-index", ("--search", "quartz", *all_dates), "search", index="warm"),
        Case("search-cjk-warm", ("--search", "迁移验证", *all_dates), "search", index="warm"),
        Case("search-fallback-warm", ("--search", "q", *all_dates), "search", index="warm"),
        Case("collect-dry-run", ("--collect", "--dry-run", *collect_dates), "collect"),
        Case("collect-emit-prompt", ("--collect", "--emit-prompt", *collect_dates), "handoff"),
    ]


def expected_uris(profile: Profile, *, provider: str | None = None, matching: bool = False) -> set[str]:
    result = set()
    for name, count in (("codex", profile.sessions_per_provider + 1), ("opencode", profile.sessions_per_provider)):
        if provider is not None and provider != name:
            continue
        for index in range(count):
            if matching and index % 10:
                continue
            identity = codex_id(index) if name == "codex" else f"ses_bench_{index:06d}"
            result.add(f"{name}://{identity}")
    return result


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def content_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def check_exports(case: Case, profile: Profile, root: Path) -> dict[str, Any]:
    indices = (
        range(profile.sessions_per_provider + 1) if case.check == "export-batch" else [profile.sessions_per_provider]
    )
    expected = {codex_id(index): session_messages(profile, index) for index in indices}
    files = sorted((root / "exports").rglob("*.json"))
    require(len(files) == len(expected), f"expected {len(expected)} JSON exports, found {len(files)}")
    payloads = {}
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        identity = payload.get("id")
        require(identity in expected and identity not in payloads, f"unexpected or duplicate export: {identity}")
        messages = [
            (message.get("role"), "".join(part.get("text", "") for part in message.get("parts", [])))
            for message in payload.get("messages", [])
        ]
        require(messages == expected[identity], f"exported messages differ from fixture: {identity}")
        payloads[identity] = payload
    markdown = sorted((root / "exports").rglob("*.md"))
    require(len(markdown) == (1 if case.check == "export-large" else 0), "unexpected Markdown export count")
    markdown_digest = None
    if markdown:
        body = markdown[0].read_text(encoding="utf-8")
        require(
            all(text in body for _, text in expected[codex_id(profile.sessions_per_provider)]), "incomplete Markdown"
        )
        markdown_digest = content_digest(body)
    return {"files": len(files) + len(markdown), "json_sha256": content_digest(payloads), "md_sha256": markdown_digest}


def check_handoff(output: str, profile: Profile, root: Path) -> dict[str, Any]:
    envelopes = [json.loads(line) for line in output.splitlines() if line.startswith("{")]
    require(bool(envelopes), "handoff has no envelopes")
    require(all(item["length"] == len(item["content"]) for item in envelopes), "handoff envelope length mismatch")
    context, *entries = [json.loads(item["content"]) for item in envelopes]
    expected = expected_uris(profile)
    require(context["session_count"] == len(entries) == len(expected), "handoff session count mismatch")
    require({entry["uri"] for entry in entries} == expected, "handoff session identities differ")
    require(context["discovery_failed_count"] == context["query_read_failed_count"] == 0, "handoff reports failures")
    context.pop("generated_at")
    for entry in entries:
        require(entry["read_argv"][-3:] == [entry["uri"], "--format", "print"], "invalid handoff read command")
        entry["read_argv"] = ["<CLI>", *entry["read_argv"][-3:]]
        entry.pop("read_command")
    normalized = json.dumps([context, *entries], ensure_ascii=False, sort_keys=True).replace(str(root), "<ROOT>")
    require(not (root / "report.md").exists(), "emit-prompt unexpectedly wrote a report")
    return {"sessions": len(entries), "manifest_sha256": content_digest(normalized)}


def validate(case: Case, profile: Profile, root: Path, output: str, exit_code: int) -> dict[str, Any]:
    require(exit_code == 0, f"{case.name} exited with {exit_code}")
    if case.check == "version":
        require(re.fullmatch(r"agent-dump \S+\s*", output) is not None, "invalid version output")
        return {"version_command": True}
    if case.check == "help":
        require(
            all(option in output for option in ("--list", "--search", "--collect", "--format", "--head")),
            "incomplete help",
        )
        return {"help_options": True}
    if case.check in {"list", "search"}:
        found = re.findall(r"(?:codex|opencode)://[A-Za-z0-9_-]+", output)
        expected = expected_uris(profile, provider=case.provider, matching=case.check == "search")
        require(
            set(found) == expected and len(found) == len(expected),
            f"{case.name}: wrong or duplicate session identities",
        )
        return {"sessions": len(found), "uris_sha256": content_digest(sorted(found))}
    if case.check in {"export-large", "export-batch"}:
        return check_exports(case, profile, root)
    if case.check == "handoff":
        return check_handoff(output, profile, root)
    if case.check in {"head", "print"}:
        require(f"codex://{codex_id(profile.sessions_per_provider)}" in output, "wrong URI")
        if case.check == "print":
            require(
                all(body in output for _, body in session_messages(profile, profile.sessions_per_provider)),
                "incomplete print",
            )
        else:
            require("end-" not in output, "head unexpectedly contains transcript body")
    count = 2 * profile.sessions_per_provider + 1
    if case.check == "stats":
        require(f"Total sessions: {count}" in output, "incorrect stats count")
    if case.check == "reindex":
        require(f"Total indexed: {count} sessions." in output, "incomplete indexing")
    if case.check == "collect":
        require(f"Sessions: {count}\n" in output, "incorrect collect count")
        require(re.search(r"Chunks: [1-9][0-9]*", output) is not None, "collect produced no chunks")
        require(not (root / "report.md").exists(), "dry-run unexpectedly wrote a report")
    return {"stdout_sha256": content_digest(output.replace(str(root), "<ROOT>"))}
