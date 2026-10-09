.DEFAULT_GOAL := help

SOURCES = src tests

.PHONY: help test check format build docs docs-serve clean

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' Makefile | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-10s\033[0m %s\n", $$1, $$2}'

test: ## Run tests with 100% branch coverage
	python -m pytest

check: ## Check formatting and types
	black --target-version py312 --check $(SOURCES)
	mypy $(SOURCES)

format: ## Format sources with Black
	black --target-version py312 $(SOURCES)

build: ## Build the sdist and wheel into dist/
	uv build

docs: ## Build the documentation site into site/
	mkdocs build --strict

docs-serve: ## Serve the documentation with live reload
	mkdocs serve

clean: ## Remove build outputs and caches
	rm -rf dist build site .coverage htmlcov .pytest_cache .mypy_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
