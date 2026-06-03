# Contributing to kanon

Thank you for contributing. This guide covers the conventions and workflows
used in this repository.

For the trust model and security invariants that govern all contributions,
see `docs/security-model.md`.

## Development setup

1. Install `uv` (the project uses uv for dependency management).
2. Clone the repository and run `uv sync` to install all dependencies.
3. Install the git pre-push hook:

   ```bash
   cp git-hooks/pre-push .git/hooks/pre-push
   chmod +x .git/hooks/pre-push
   ```

4. Run the full test suite to verify your environment:

   ```bash
   uv run pytest tests/ -v
   uv run ruff check src tests
   uv run ruff format --check src tests
   uv run mypy src
   uv run bandit -r src -ll
   ```

## Code standards

- Follow the 12-Factor App principles: no hard-coded configuration, all
  config from environment variables or YAML files.
- All constants live in `src/kanon_cli/constants.py`.
- No provider-specific API calls or CLI invocations in production code
  (see `docs/security-model.md` -- Provider-agnosticism).
- Use TDD: write a failing test before the implementation.

## Running tests

```bash
# Unit tests only
uv run pytest tests/unit -v

# Integration tests
uv run pytest tests/integration -v

# Functional (end-to-end) tests
uv run pytest tests/functional -v

# Full suite
uv run pytest tests/ -v
```

### How to add a multi-provider parity test

Multi-provider parity tests verify that kanon behaves identically regardless
of which git hosting provider the underlying repositories live on (spec
Section 10). When writing such a test you may need to include fixture files
that intentionally reference provider-specific hostnames or CLI tools for
comparison purposes.

### Fixture files

Place provider-specific fixture files (e.g., sample API responses, mock
credential files, provider-URL examples) under `tests/fixtures/`. Files
under `tests/fixtures/` are always excluded from the provider-agnosticism
CI scan described in `docs/security-model.md`.

### Allowlist entries for non-fixture exemptions

If a test file outside `tests/fixtures/` must reference a provider-specific
token (e.g., to verify that kanon correctly rejects a provider URL in input),
add an exemption line to `tests/integration/provider_allowlist.txt`:

```
<repo-relative-path>:<justification>
```

**Format rules:**

- `<repo-relative-path>`: the exact repo-relative path of the file (e.g.,
  `tests/integration/test_url_rejection.py`).
- `<justification>`: non-empty free text explaining why a human reviewer
  accepted this exemption. Whitespace-only justifications are rejected by
  the parser.
- Lines starting with `#` are comments and are ignored.
- Blank lines are ignored.
- A malformed line (missing colon, empty justification) causes
  `tests/functional/test_provider_agnostic.py` to fail with a `ValueError`
  naming the line number.

**Review requirement:** adding an entry requires a code review. Production
source files under `src/kanon_cli/` MUST NOT appear in the allowlist.

### Example allowlist entry

```
tests/integration/test_url_rejection.py:Contains sample provider URLs in assertions that verify kanon rejects non-git provider REST endpoints; this is a negative test, not a production call.
```

### Running the provider-agnosticism scan

The scan runs automatically as part of `pytest tests/functional -v`. To run
it in isolation:

```bash
uv run pytest tests/functional/test_provider_agnostic.py -v
```

A passing run confirms that no production source file has introduced a
provider-specific dependency since the last review.
