# Show all available recipes
[no-cd]
default:
    @just --list --unsorted

# Run code linting with Ruff
lint:
    @echo "🔍 Running code linting..."
    uv run ruff check .
    @echo "✅ Lint check complete!"

# Auto-fix linting issues with Ruff
lint-fix:
    @echo "🔧 Auto-fixing linting issues..."
    uv run ruff check . --fix
    @echo "✅ Lint fixes applied!"

# Format code with Ruff
lint-format:
    @echo "🎨 Formatting code..."
    uv run ruff format .
    @echo "✅ Code formatting complete!"

# Run type checking with pyright and ty
check:
    @echo "🔍 Running type checks..."
    uv run pyright
    uv run ty check .
    @echo "✅ Type checking complete!"

# Run all tests with pytest
test:
    @echo "🧪 Running tests..."
    uv run pytest -q
    @echo "✅ Tests complete!"

# Run lint check test
isok: lint-fix lint-format check test

# Run the agent-dump CLI
run:
    @echo "🚀 Starting agent-dump..."
    uv run agent-dump

# Build a native binary for the current platform
build-native:
    @echo "📦 Building native binary..."
    PYINSTALLER_CONFIG_DIR=.pyinstaller UV_CACHE_DIR=.uv-cache uv run --with pyinstaller pyinstaller packaging/pyinstaller.spec --clean --noconfirm
    @echo "✅ Native binary build complete!"

# Sync npm package versions from Python version metadata
build-npm:
    @echo "📦 Syncing npm workspace versions..."
    npm --prefix npm run sync-version
    @echo "✅ npm workspace is ready!"

# Run npm wrapper unit tests and local packaging smoke checks
test-npm-smoke:
    @echo "🧪 Running npm wrapper tests..."
    npm --prefix npm test
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
    uv run python -c "import shutil; import os; shutil.rmtree('dist') if os.path.exists('dist') else None"
    @echo "✅ Build artifacts cleaned!"

# Build package wheel file
build: clean-build
    @echo "📦 Building package..."
    uv build --no-sources
    @echo "✅ Build complete!"

# Publish package to PyPI
publish:
    @echo "🚀 Publishing to PyPI..."
    uv publish
    @echo "✅ Published successfully!"

# Build and publish package in one step
build-and-publish: build publish
