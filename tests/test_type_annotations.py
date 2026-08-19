"""Production type-annotation contract tests."""

import ast
from pathlib import Path


def test_production_functions_have_complete_annotations() -> None:
    source_root = Path(__file__).resolve().parent.parent / "src"
    omissions: list[str] = []

    for path in sorted(source_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            arguments = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
            missing_arguments = [
                argument.arg
                for argument in arguments
                if argument.arg not in {"self", "cls"} and argument.annotation is None
            ]
            if node.args.vararg is not None and node.args.vararg.annotation is None:
                missing_arguments.append(f"*{node.args.vararg.arg}")
            if node.args.kwarg is not None and node.args.kwarg.annotation is None:
                missing_arguments.append(f"**{node.args.kwarg.arg}")

            if missing_arguments:
                omissions.append(f"{path.relative_to(source_root)}:{node.lineno}: parameters {missing_arguments}")
            if node.returns is None:
                omissions.append(f"{path.relative_to(source_root)}:{node.lineno}: return type")

    assert omissions == [], "Production functions must have complete type annotations:\n" + "\n".join(omissions)
