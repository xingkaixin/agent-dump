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
    uv build
    @echo "✅ Build complete!"

# Publish package to PyPI
publish:
    @echo "🚀 Publishing to PyPI..."
    uv publish
    @echo "✅ Published successfully!"

# Build and publish package in one step
build-and-publish: build publish
