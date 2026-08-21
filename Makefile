SHELL := /bin/bash
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := help

.PHONY: check-completion-snapshots help install install-dev lint lint-check lint-no-comments lint-markdown format format-check check test test-unit test-unit-cov test-unit-vendored test-integration test-functional test-cov test-scenarios test-operator-path validate clean build distcheck publish pre-commit-check install-hooks security-scan update-completion-snapshots

# Minimum total coverage enforced by `test-unit-cov`. Overridable so the
# threshold is not hard-coded at its only call site. It is measured over kanon's
# own source; the vendored tree is omitted in [tool.coverage.run].
COVERAGE_MIN ?= 93

# The vendored repo tool's tests. Roughly 6,700 of the suite's ~17,300 tests cover
# a tree that changed in 3 of the last 184 commits, so they are their own tier and
# CI runs them only when that tree is touched. Referenced by more than one target,
# so the path lives here rather than being repeated.
#
# test-unit-cov selects by MARKER and excludes this path -- it must not also take a
# positional path argument. A positional narrows collection to that directory and
# silently drops every unit-marked test living elsewhere (tests/security,
# tests/regression, tests/test_wheel_layout.py), which then run in no CI job at all.
# tests/unit/test_marker_completeness.py asserts the two tiers still sum to the whole.
VENDORED_TESTS := tests/unit/repo

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install the project and its runtime dependencies from uv.lock
	uv sync --locked --no-dev

install-dev: ## Install development dependencies from uv.lock (editable project + dev tool group)
	uv sync --locked --all-groups

lint: lint-check format-check ## Run all lint checks (ruff check + ruff format --check)

lint-check: lint-no-comments ## Lint Python files (ruff check + no-comments gate)
	uv run ruff check .

lint-no-comments: ## Forbid '#' comments in all first-party kanon Python (allows line-1 shebang + PEP 263 encoding cookie)
	uv run python tools/lint/check_no_comments.py

lint-markdown: ## Lint kanon's own Markdown under docs/ and README.md (pymarkdownlnt, config in [tool.pymarkdown]: MD013 off, MD024 siblings_only; vendored docs/repo/ excluded)
	uv run pymarkdownlnt scan -r -e 'docs/repo/*' docs/ README.md

format: ## Auto-format Python files (ruff format)
	uv run ruff format .

format-check: ## Verify formatting without modifying files (ruff format --check)
	uv run ruff format --check .

check: lint ## Run all static analysis checks

validate: check test-unit ## Run per-unit validation (lint + unit tests). Full suite + coverage are enforced in CI (test / test-integration / test-functional / test-scenarios).

test: ## Run full test suite with coverage
	uv run pytest -n auto --dist loadscope --cov=kanon_cli --cov-report=term-missing

test-unit: ## Run every unit test, first-party and vendored
	uv run pytest -n auto --dist loadscope -m "unit"

test-unit-cov: ## Run first-party unit tests with coverage and enforce the COVERAGE_MIN gate (CI's unit job)
	uv run pytest -n auto --dist loadscope -m "unit" --ignore=$(VENDORED_TESTS) \
		--cov=kanon_cli --cov-report=term-missing --cov-fail-under=$(COVERAGE_MIN)

test-unit-vendored: ## Run the vendored repo tool's unit tests (gated in CI on that tree changing)
	uv run pytest -n auto --dist loadscope -m "unit" $(VENDORED_TESTS)

test-integration: ## Run integration tests only
	uv run pytest -n auto --dist loadscope -m "integration"

security-scan: ## Run security scan with bandit (high severity, high confidence, excludes vendored repo submodule)
	uv run bandit -r src/kanon_cli/ -x src/kanon_cli/repo -lll -iii

test-functional: SMOKE_TEST_TIMEOUT ?= 300
test-functional: ## Run functional tests only
	SMOKE_TEST_TIMEOUT=$(SMOKE_TEST_TIMEOUT) uv run pytest -n auto --dist loadscope -m "functional"

test-scenarios: ## Run end-to-end scenario tests (mirrors docs/integration-testing.md)
	uv run pytest -n auto --dist loadscope -m "scenario"

test-operator-path: ## Run operator-path scenario tests (E49 subprocess path tests -- fast lane for tests/scenarios/test_why_url_path.py etc.)
	uv run pytest -m scenario tests/scenarios/test_why_url_path.py tests/scenarios/test_doctor_cache.py tests/scenarios/test_rls_exact_vs_range.py

test-cov: ## Run tests with coverage report
	uv run pytest -n auto --dist loadscope --cov=kanon_cli --cov-report=term-missing

clean: ## Remove build artifacts and caches
	find . -depth -type d -name __pycache__ -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache htmlcov dist build *.egg-info src/*.egg-info
	rm -f .coverage
	rm -rf .coverage-data coverage.json
	find . -depth -type f -name '*.pyc' -delete

build: ## Build the package
	uv run python -m build

distcheck: ## Check the built distribution
	uv run twine check dist/*
	uv run python scripts/check_archive_no_duplicates.py dist/

publish: clean build distcheck ## Build package (publishing is automated via CI pipeline)


pre-commit-check: ## Run all pre-commit hooks
	uv run pre-commit run --all-files

install-hooks: ## Install git hooks for pre-commit and pre-push
	@echo "Installing git hooks..."
	@git config --unset-all core.hooksPath || true
	@uv run pre-commit install || echo "pre-commit not found, skipping pre-commit installation"
	@git config core.hooksPath git-hooks
	@chmod +x git-hooks/pre-commit git-hooks/pre-push
	@echo "Git hooks installed successfully!"

update-completion-snapshots: ## Regenerate bash + zsh completion fixture files (deliberate, review the diff)
	uv run kanon completion bash > tests/fixtures/completion/expected-bash.sh.tmp
	mv tests/fixtures/completion/expected-bash.sh.tmp tests/fixtures/completion/expected-bash.sh
	uv run kanon completion zsh > tests/fixtures/completion/expected-zsh.sh.tmp
	mv tests/fixtures/completion/expected-zsh.sh.tmp tests/fixtures/completion/expected-zsh.sh

check-completion-snapshots: ## Verify the completion fixtures match generated output
	@uv run kanon completion bash > tests/fixtures/completion/expected-bash.sh.check
	@uv run kanon completion zsh > tests/fixtures/completion/expected-zsh.sh.check
	@status=0; \
	for shell in bash zsh; do \
		if ! diff -u "tests/fixtures/completion/expected-$$shell.sh" "tests/fixtures/completion/expected-$$shell.sh.check"; then \
			status=1; \
		fi; \
	done; \
	rm -f tests/fixtures/completion/expected-bash.sh.check tests/fixtures/completion/expected-zsh.sh.check; \
	if [ "$$status" -ne 0 ]; then \
		echo "ERROR: completion fixtures are stale. Run 'make update-completion-snapshots' and review the diff before committing."; \
		exit 1; \
	fi; \
	echo "completion fixtures match generated output"
