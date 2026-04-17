SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := help

.PHONY: help install install-dev lint lint-check format format-check check test test-unit test-integration test-functional test-cov validate clean build distcheck publish pre-commit-check install-hooks coverage-json security-scan

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install runtime dependencies
	pip install -r requirements.txt

install-dev: ## Install development dependencies (editable + ruff + pytest)
	pip install -r requirements-dev.txt

lint: lint-check format-check ## Run all lint checks (ruff check + ruff format --check)

lint-check: ## Lint Python files (ruff check)
	ruff check .

format: ## Auto-format Python files (ruff format)
	ruff format .

format-check: ## Verify formatting without modifying files (ruff format --check)
	ruff format --check .

check: lint ## Run all static analysis checks

validate: check test ## Run full validation pipeline (lint + tests)

test: ## Run full test suite with coverage
	uv run pytest --cov=kanon_cli --cov-report=term-missing

test-unit: ## Run unit tests only
	uv run pytest -m unit

test-integration: ## Run integration tests only
	uv run pytest -m integration

security-scan: ## Run security scan with bandit (high severity, high confidence, excludes vendored repo submodule)
	uv run bandit -r src/kanon_cli/ -x src/kanon_cli/repo -lll -iii

test-functional: SMOKE_TEST_TIMEOUT ?= 300
test-functional: ## Run functional tests only
	SMOKE_TEST_TIMEOUT=$(SMOKE_TEST_TIMEOUT) uv run pytest -m functional

test-cov: ## Run tests with coverage report
	uv run pytest --cov=kanon_cli --cov-report=term-missing

clean: ## Remove build artifacts and caches
	find . -depth -type d -name __pycache__ -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache htmlcov dist build *.egg-info src/*.egg-info
	rm -f .coverage
	rm -rf .coverage-data coverage.json
	find . -depth -type f -name '*.pyc' -delete

build: ## Build the package
	python -m build

distcheck: ## Check the built distribution
	twine check dist/*

publish: clean build distcheck ## Build package (publishing is automated via CI pipeline)

coverage-json: ## Generate JSON coverage report
	uv run pytest -m unit --cov=kanon_cli --cov-report=json
	@echo "Coverage report generated in coverage.json"

pre-commit-check: ## Run all pre-commit hooks
	pre-commit run --all-files

install-hooks: ## Install git hooks for pre-commit and pre-push
	@echo "Installing git hooks..."
	@git config --unset-all core.hooksPath || true
	@pre-commit install || echo "pre-commit not found, skipping pre-commit installation"
	@git config core.hooksPath git-hooks
	@chmod +x git-hooks/pre-commit git-hooks/pre-push
	@echo "Git hooks installed successfully!"
