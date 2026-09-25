from cli_fixture import call, export_parity, output
import pytest

PATCH = """*** Begin Patch
*** Add File: 新文件.py
+print("new")
*** Delete File: obsolete.py
*** Update File: old.py
@@ first
-old = 1
+new = 2
 context
@@ second
+more
*** End of File
*** Update File: move-only.py
*** Move to: moved.py
*** Update File: rename-edit.py
*** Move to: renamed.py
@@
-before
+after
*** End Patch
ignored trailing text
"""


@pytest.mark.parametrize("lang", ["en", "zh"])
@pytest.mark.parametrize(
    "patch",
    [
        PATCH,
        PATCH.replace("\n", "\r\n"),
        "",
        "invalid",
        "*** Begin Patch\n",
        "*** Begin Patch\ninvalid\n*** End Patch",
        "*** Begin Patch\n*** Add File: x\ninvalid\n*** End Patch",
        "*** Begin Patch\n*** End Patch",
    ],
)
def test_patch_content_and_localized_parse_errors(cli, patch, lang):
    export_parity(
        cli,
        [call("apply_patch", arguments=patch, custom=True), output('{"output":"applied", "metadata":0}', custom=True)],
        lang=lang,
    )
