.PHONY: fmt lint test test-integration test-all typecheck check install dev build clean

fmt:
	uv run ruff format src/ tests/

lint:
	uv run ruff check src/ tests/

typecheck:
	uv run pyright src/ccbot/

test:
	uv run pytest tests/ -m "not integration"

test-integration:
	uv run pytest tests/integration/ -v

test-all:
	uv run pytest tests/ -v

check: fmt lint typecheck test test-integration

install:
	uv sync

dev:
	uv sync --extra dev

build:
	uv build

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache .ruff_cache .mypy_cache htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} +
