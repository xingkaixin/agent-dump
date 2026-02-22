lint:
    uv run ruff check .

lint-fix:
    uv run ruff check . --fix

lint-format:
    uv run ruff format .

check:
    uv run pyright
    uv run ty check .

test:
    uv run pytest -vv

run:
    uv run agent-dump

logo:
    rsvg-convert -o assets/logo.png assets/logo.svg

build:
    uv build

publish:
    uv publish
