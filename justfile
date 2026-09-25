# Show all available recipes
[no-cd]
default:
    @just --list --unsorted

# Check Rust formatting, Clippy and Python tooling style
lint: lint-tools
    cargo fmt --all --check
    cargo clippy --locked --workspace --all-targets -- -D warnings

lint-tools:
    @echo "🔍 Running code linting..."
    uv run ruff check .
    uv run ruff format --check .
    @echo "✅ Lint check complete!"

# Auto-fix linting issues with Ruff
lint-fix:
    @echo "🔧 Auto-fixing linting issues..."
    uv run ruff check . --fix
    @echo "✅ Lint fixes applied!"

# Format Rust and Python verification tools
fmt:
    @echo "🎨 Formatting code..."
    cargo fmt --all
    uv run ruff format .
    @echo "✅ Code formatting complete!"

lint-format: fmt

fmt-check:
    cargo fmt --all --check
    uv run ruff format --check .

# Run type checking for Rust and verification tools
check: check-tools
    cargo check --locked --workspace --all-targets

check-tools:
    @echo "🔍 Running type checks..."
    uv run ty check .
    @echo "✅ Type checking complete!"

# Verify Rust units and the isolated CLI/tooling contracts
test: reference build-rust
    cargo test --locked --workspace
    uv run pytest -q

# Install the frozen external Python CLI for differential verification
reference:
    uv run python scripts/python_reference.py --install

# Record validated synthetic CLI benchmarks (no real Provider data)
benchmark *args: build-rust
    uv run python scripts/benchmark_cli.py {{args}}

# Check the Rust CLI and compare it with Python on synthetic data
check-rust: reference
    cargo fmt --all --check
    cargo clippy --locked --workspace --all-targets -- -D warnings
    cargo test --locked --workspace
    cargo build --locked --release
    uv run pytest -q tests/cli

# Build the Rust binary for performance evaluation
build-rust:
    cargo build --locked --release

# Run npm wrapper unit tests
test-npm:
    @echo "🧪 Running npm wrapper tests..."
    npm --prefix npm test
    @echo "✅ npm wrapper tests complete!"

# Auto-fix lint issues and format code
fix: lint-fix lint-format

# Type-check and build the landing page from the committed lockfile
check-web:
    @echo "🔍 Checking landing page..."
    pnpm --dir web install --frozen-lockfile
    pnpm --dir web check
    pnpm --dir web build
    pnpm --dir web exec playwright install chromium
    pnpm --dir web test:e2e
    @echo "✅ Landing page check complete!"

# Fail when uv.lock no longer matches pyproject.toml
lock-check:
    @echo "🔍 Checking uv.lock is current..."
    uv lock --check
    @echo "✅ uv.lock matches pyproject.toml!"

# Run local CI checks; include npm and website checks when their tools are available
isok: lock-check lint check test
    @if command -v node >/dev/null 2>&1; then \
        just test-npm; \
    else \
        echo "⏭️ Skipping npm wrapper tests (Node.js not found)"; \
    fi
    @if command -v pnpm >/dev/null 2>&1; then \
        just check-web; \
    else \
        echo "⏭️ Skipping landing page check (pnpm not found)"; \
    fi

# Run the agent-dump CLI
run:
    @echo "🚀 Starting agent-dump..."
    cargo run --locked --release --

# Build a native binary for the current platform
build-native:
    @echo "📦 Building native binary..."
    cargo build --locked --release
    @echo "✅ Native binary build complete!"

# Sync npm package versions from Cargo.toml
build-npm:
    @echo "📦 Syncing npm workspace versions..."
    npm --prefix npm run sync-version
    @echo "✅ npm workspace is ready!"

# Run npm wrapper unit tests and local packaging smoke checks
test-npm-smoke: test-npm
    @echo "🧪 Running local npm smoke check..."
    npm --prefix npm run smoke
    @echo "✅ npm smoke checks complete!"

# Convert SVG logo to PNG
logo:
    @echo "🖼️ Converting logo to PNG..."
    rsvg-convert -o assets/logo.png assets/logo.svg
    @echo "✅ Logo converted!"

# Clean build artifacts
clean-build:
    @echo "🧹 Cleaning build artifacts..."
    uv run --no-project python -c "import shutil; import os; shutil.rmtree('dist') if os.path.exists('dist') else None"
    @echo "✅ Build artifacts cleaned!"

# Install the built wheel into a clean venv and run its console entrypoint
verify-wheel:
    @echo "🔍 Verifying wheel installs and runs..."
    uv run python packaging/verify_wheel.py
    @echo "✅ Wheel verification complete!"

# Verify every release artifact before anything is published
verify-artifacts: verify-wheel test-npm-smoke
    @echo "✅ Release artifacts verified!"

# Refresh the reviewed PEP 517 dependency closure and distribution hashes
update-build-constraints:
    uv pip compile packaging/build-constraints.in --universal --python-version 3.10 --generate-hashes --custom-compile-command "just update-build-constraints" --output-file packaging/build-constraints.txt

# Build package wheel file
build: clean-build
    @echo "📦 Building package..."
    uv run --group packaging python packaging/build_release.py
    @echo "✅ Build complete!"

# Publish package to PyPI
publish:
    @echo "🚀 Publishing to PyPI..."
    uv publish
    @echo "✅ Published successfully!"

# Build and publish package in one step
build-and-publish: build publish

# Build the static landing page (Astro, en + zh + ja) into web/dist
build-web:
    @echo "🛠️ Building landing page..."
    pnpm --dir web install --frozen-lockfile
    pnpm --dir web build
    @echo "✅ Landing page built!"

# Run the landing page dev server
dev-web:
    @echo "🚀 Starting landing page dev server..."
    pnpm --dir web dev

# Deploy the built static site to Cloudflare Pages
deploy-web: build-web
    @echo "🌐 Deploying web/dist to Cloudflare Pages..."
    pnpm --dir web exec wrangler pages deploy dist --project-name=agent-dump --commit-dirty=true
    @echo "✅ Web deployment complete!"
