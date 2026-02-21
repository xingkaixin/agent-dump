lint:
	uv run ruff check .

lint.fix:
	uv run ruff check . --fix

lint.fmt:
	uv run ruff format .

check:
	uv run pyright
	uv run ty check .

test:
	uv run pytest -vv

logo:
	rsvg-convert -o assets/logo.png assets/logo.svg
