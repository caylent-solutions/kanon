SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := help

.PHONY: help install install-dev lint lint-check lint-markdown format format-check check test test-unit test-integration test-functional test-cov test-scenarios test-operator-path validate clean build distcheck publish pre-commit-check install-hooks coverage-json security-scan update-completion-snapshots

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install runtime dependencies
	pip install -r requirements.txt

install-dev: ## Install development dependencies (editable + ruff + pytest)
	pip install -r requirements-dev.txt

lint: lint-check format-check ## Run all lint checks (ruff check + ruff format --check)

lint-check: ## Lint Python files (ruff check)
	ruff check .

lint-markdown: ## Lint kanon's own Markdown under docs/ and README.md (pymarkdownlnt, config in [tool.pymarkdown]: MD013 off, MD024 siblings_only; vendored docs/repo/ excluded)
	uv run pymarkdownlnt scan -r -e 'docs/repo/*' docs/ README.md

format: ## Auto-format Python files (ruff format)
	ruff format .

format-check: ## Verify formatting without modifying files (ruff format --check)
	ruff format --check .

check: lint ## Run all static analysis checks

validate: check test-unit ## Run per-unit validation (lint + unit tests). Full suite + coverage are enforced in CI (test / test-integration / test-functional / test-scenarios).

test: ## Run full test suite with coverage
	uv run pytest --cov=kanon_cli --cov-report=term-missing

test-unit: ## Run unit tests only
	uv run pytest -m "unit"

test-integration: ## Run integration tests only
	uv run pytest -m "integration"

security-scan: ## Run security scan with bandit (high severity, high confidence, excludes vendored repo submodule)
	uv run bandit -r src/kanon_cli/ -x src/kanon_cli/repo -lll -iii

test-functional: SMOKE_TEST_TIMEOUT ?= 300
test-functional: ## Run functional tests only
	SMOKE_TEST_TIMEOUT=$(SMOKE_TEST_TIMEOUT) uv run pytest -m "functional"

test-scenarios: ## Run end-to-end scenario tests (mirrors docs/integration-testing.md)
	uv run pytest -m "scenario"

test-operator-path: ## Run operator-path scenario tests (E49 subprocess path tests -- fast lane for tests/scenarios/test_why_url_path.py etc.)
	uv run pytest -m scenario tests/scenarios/test_why_url_path.py tests/scenarios/test_doctor_cache.py tests/scenarios/test_rls_exact_vs_range.py

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
	python scripts/check_archive_no_duplicates.py dist/

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

update-completion-snapshots: ## Regenerate bash + zsh completion fixture files
	uv run kanon completion bash > tests/fixtures/completion/expected-bash.sh
	uv run kanon completion zsh > tests/fixtures/completion/expected-zsh.sh
