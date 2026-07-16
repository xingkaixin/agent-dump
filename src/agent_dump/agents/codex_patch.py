"""Parse Codex apply_patch tool input into exported content blocks."""

from typing import Any


def parse_apply_patch_input(raw_input: str) -> dict[str, Any]:
    """Parse apply_patch input into a structured patch payload."""
    result = _build_empty_patch_arguments(raw_input)
    lines = raw_input.splitlines()

    try:
        if not lines:
            raise ValueError("patch 为空")
        if lines[0] != "*** Begin Patch":
            raise ValueError("patch 缺少 Begin Patch 头")

        index = 1
        operations: list[dict[str, Any]] = []
        saw_end_patch = False

        while index < len(lines):
            line = lines[index]
            if line == "*** End Patch":
                saw_end_patch = True
                index += 1
                break
            if line.startswith("*** Add File: "):
                path = line.removeprefix("*** Add File: ")
                operation = _build_patch_operation(action="add", path=path)
                index = _parse_patch_hunks(lines, index + 1, operation)
                operations.append(operation)
                continue
            if line.startswith("*** Delete File: "):
                path = line.removeprefix("*** Delete File: ")
                operation = _build_patch_operation(action="delete", path=path)
                index = _parse_patch_hunks(lines, index + 1, operation)
                operations.append(operation)
                continue
            if line.startswith("*** Update File: "):
                old_path = line.removeprefix("*** Update File: ")
                index += 1
                new_path = old_path
                if index < len(lines) and lines[index].startswith("*** Move to: "):
                    new_path = lines[index].removeprefix("*** Move to: ")
                    index += 1

                operation = _build_patch_operation(
                    action="move" if new_path != old_path else "update",
                    path=new_path,
                    old_path=old_path if new_path != old_path else None,
                )
                index = _parse_patch_hunks(lines, index, operation)
                if operation["old_path"] and operation["hunks"]:
                    operation["action"] = "update"
                operations.append(operation)
                continue
            raise ValueError(f"无法解析 patch 操作头: {line}")

        if not saw_end_patch:
            raise ValueError("patch 缺少 End Patch 尾")

        result["content"] = _build_patch_content_blocks(operations)
        return result
    except ValueError as exc:
        return _build_empty_patch_arguments(raw_input, parse_error=str(exc))


def _build_empty_patch_arguments(raw_input: str, parse_error: str | None = None) -> dict[str, Any]:
    arguments = {
        "kind": "apply_patch",
        "raw": raw_input,
        "content": [],
    }
    if parse_error:
        arguments["parse_error"] = parse_error
    return arguments


def _is_patch_operation_header(line: str) -> bool:
    return line.startswith(
        (
            "*** Add File: ",
            "*** Delete File: ",
            "*** Update File: ",
            "*** End Patch",
        )
    )


def _build_patch_operation(
    *,
    action: str,
    path: str,
    old_path: str | None = None,
) -> dict[str, Any]:
    return {
        "action": action,
        "path": path,
        "old_path": old_path,
        "hunks": [],
    }


def _append_patch_line(
    operation: dict[str, Any],
    *,
    header: str | None,
    kind: str,
    text: str,
) -> None:
    hunks = operation["hunks"]
    if not hunks or hunks[-1]["header"] != header:
        hunks.append({"header": header, "lines": []})
    hunks[-1]["lines"].append({"kind": kind, "text": text})


def _parse_patch_hunks(lines: list[str], start_index: int, operation: dict[str, Any]) -> int:
    index = start_index
    current_header: str | None = None

    while index < len(lines):
        line = lines[index]
        if _is_patch_operation_header(line):
            break
        if line == "*** End of File":
            index += 1
            continue
        if line.startswith("@@"):
            current_header = line
            if not operation["hunks"] or operation["hunks"][-1]["header"] != current_header:
                operation["hunks"].append({"header": current_header, "lines": []})
            index += 1
            continue
        if line.startswith("+"):
            _append_patch_line(operation, header=current_header, kind="add", text=line[1:])
            index += 1
            continue
        if line.startswith("-"):
            _append_patch_line(operation, header=current_header, kind="remove", text=line[1:])
            index += 1
            continue
        if line.startswith(" "):
            _append_patch_line(operation, header=current_header, kind="context", text=line[1:])
            index += 1
            continue
        raise ValueError(f"无法解析 patch 行: {line}")

    return index


def _build_write_file_content(operation: dict[str, Any]) -> str:
    lines: list[str] = []
    for hunk in operation["hunks"]:
        for line in hunk["lines"]:
            if line["kind"] == "remove":
                continue
            lines.append(line["text"])
    return "\n".join(lines)


def _build_edit_file_diff(operation: dict[str, Any]) -> str:
    source_path = operation.get("old_path") or operation["path"]
    target_path = operation["path"]
    diff_lines = [
        f"Index: {target_path}",
        "===================================================================",
        f"--- {source_path}",
        f"+++ {target_path}",
    ]

    for hunk in operation["hunks"]:
        header = hunk.get("header")
        if header:
            diff_lines.append(header)
        for line in hunk["lines"]:
            prefix = {
                "remove": "-",
                "add": "+",
                "context": " ",
            }.get(line["kind"], "")
            diff_lines.append(f"{prefix}{line['text']}")

    return "\n".join(diff_lines)


def _build_patch_content_blocks(operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []

    for operation in operations:
        action = operation["action"]
        path = operation["path"]
        old_path = operation.get("old_path")

        if action == "add":
            blocks.append(
                {
                    "type": "write_file",
                    "path": path,
                    "old_path": None,
                    "input": {"content": _build_write_file_content(operation)},
                }
            )
            continue

        if action == "delete":
            blocks.append(
                {
                    "type": "delete_file",
                    "path": path,
                    "old_path": None,
                    "input": {"content": ""},
                }
            )
            continue

        if action == "move":
            blocks.append(
                {
                    "type": "move_file",
                    "path": path,
                    "old_path": old_path,
                    "input": {"content": ""},
                }
            )
            continue

        blocks.append(
            {
                "type": "edit_file",
                "path": path,
                "old_path": old_path,
                "input": {"content": _build_edit_file_diff(operation)},
            }
        )

    return blocks
