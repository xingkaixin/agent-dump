"""Tests for the Codex apply_patch parser seam."""

from agent_dump.agents.codex_patch import parse_apply_patch_input


def test_parse_apply_patch_input_builds_export_blocks() -> None:
    raw_input = """*** Begin Patch
*** Add File: new.py
+print("new")
*** Update File: old.py
@@
-old = 1
+new = 2
*** End Patch
"""

    result = parse_apply_patch_input(raw_input)

    assert result == {
        "kind": "apply_patch",
        "raw": raw_input,
        "content": [
            {
                "type": "write_file",
                "path": "new.py",
                "old_path": None,
                "input": {"content": 'print("new")'},
            },
            {
                "type": "edit_file",
                "path": "old.py",
                "old_path": None,
                "input": {
                    "content": (
                        "Index: old.py\n"
                        "===================================================================\n"
                        "--- old.py\n"
                        "+++ old.py\n"
                        "@@\n"
                        "-old = 1\n"
                        "+new = 2"
                    )
                },
            },
        ],
    }


def test_parse_apply_patch_input_preserves_invalid_raw_input() -> None:
    raw_input = "*** Begin Patch\ninvalid\n*** End Patch\n"

    result = parse_apply_patch_input(raw_input)

    assert result["raw"] == raw_input
    assert result["content"] == []
    assert result["parse_error"] == "无法解析 patch 操作头: invalid"
