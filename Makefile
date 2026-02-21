lint:
	uv run ruff check .

lint.fix:
	uv run ruff check . --fix

lint.fmt:
	uv run ruff format .

check:
	uv run pyright
	uv run ty check .
