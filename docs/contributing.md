# Contributing to kanon

Thank you for contributing. This guide covers the conventions and workflows
used in this repository.

For the trust model and security invariants that govern all contributions,
see `docs/security-model.md`.

## Development setup

1. Install `uv` (the project uses uv for dependency management).
2. Clone the repository and run `uv sync` to install all dependencies.
3. Install the git hooks:

   ```bash
   make install-hooks
   ```

   This points `core.hooksPath` at the tracked `git-hooks/` directory. Copying
   the hook into `.git/hooks/` instead does nothing once `core.hooksPath` is set,
   because git then ignores `.git/hooks/` entirely.

4. Verify your environment with the same targets CI runs:

   ```bash
   make lint
   make security-scan
   make test-unit-cov
   ```

   These resolve every tool from `uv.lock`, so a local pass means the same
   versions CI uses. The full suite (`make test`) runs nightly and is not needed
   to validate a setup.

## Code standards

- Follow the 12-Factor App principles: no hard-coded configuration, all
  config from environment variables or YAML files.
- All constants live in `src/kanon_cli/constants.py`.
- No provider-specific API calls or CLI invocations in production code
  (see `docs/security-model.md` -- Provider-agnosticism).
- Use TDD: write a failing test before the implementation.

## Running tests

Use the make targets rather than invoking pytest directly: they carry the marker
selection, the vendored-tree split and the coverage gate that CI applies, and a
bare `pytest tests/unit` silently includes the vendored tier.

```bash
make test-unit-cov        # kanon's own unit tests + the coverage gate
make test-unit-vendored   # the vendored repo tool's unit tests
make test-integration
make test-functional
make test-scenarios
make test                 # every tier in one session (nightly / main only)
```

### Test tiers and what runs when

Every test declares its tier with exactly one marker -- `unit`, `integration`,
`functional`, or `scenario`. This is enforced by
`tests/unit/test_marker_completeness.py`: a test with no marker is collected by
no CI job, and once tiers are gated on which paths a change touches, its absence
is indistinguishable from success.

| Make target | Scope |
| --- | --- |
| `make test-unit-cov` | kanon's own unit tests + the `COVERAGE_MIN` gate |
| `make test-unit-vendored` | the vendored repo tool's unit tests |
| `make test-unit` | both of the above, without the coverage gate |
| `make test-integration` / `test-functional` / `test-scenarios` | the named tier |
| `make test` | every tier in one pytest session (cross-suite isolation guard) |

**The vendored repo tool has its own tier.** `tests/unit/repo` is roughly 6,700
of the suite's ~17,300 tests and covers a tree that changed in 3 of the last 184
commits (`git log --oneline main -184 -- src/kanon_cli/repo/`).
Pull request validation runs it only when `src/kanon_cli/repo` or its tests are
touched, or when something global changes (`tests/conftest.py`, dependencies,
`Makefile`, CI).

**Coverage measures kanon's own source.** `[tool.coverage.run]` omits
`src/kanon_cli/repo`, which is 10,873 of 18,768 measured statements. Including it
made the project gate largely a measure of a vendored tree: the same threshold
read 92% across both and 94% across kanon's own.

**Documentation-only changes skip the test tiers.** A pull request touching only
`docs/`, Markdown, `LICENSE`, or `CODEOWNERS` runs lint and the security scan but
no test tier. The classification fails closed -- an empty diff, a missing merge
base, or any unrecognised path runs everything.

**The full suite is not a pull request gate.** It runs on every push to `main`
and nightly (`.github/workflows/nightly-regression.yml`). It guards cross-suite
isolation regressions, which only surface when every tier shares one session --
a class the per-tier jobs cannot see by construction.

### What runs before a push

The `pre-push` hook runs lint, the security scan, and kanon's own unit tests with
the coverage gate -- fast enough to wait for. The integration and functional
tiers used to run here as well, which put roughly twenty minutes between deciding
to push and pushing; CI runs both on every pull request regardless. Run
`make test-integration` and `make test-functional` yourself before opening a pull
request when a change touches subprocess or filesystem behaviour.

### Test timeouts and subprocess containment

Nothing in the suite is allowed to block indefinitely. Four settings
enforce that, each with a working default so a bare `pytest` run is still
protected:

**`KANON_TEST_TIMEOUT`** (default: `600`) -- Per-test deadline in
seconds, applied by `pytest-timeout`. Exported to `PYTEST_TIMEOUT` by
`tests/conftest.py`. On expiry the worker dumps every thread's stack,
which is what identifies a deadlock as opposed to a slow test.

**`KANON_TEST_SUBPROCESS_TIMEOUT`** (default: `300`) -- Deadline in
seconds for a single `kanon` subprocess spawned by
`tests/functional/conftest.py::_run_kanon` or
`tests/scenarios/conftest.py::run_kanon`. Keep it below
`KANON_TEST_TIMEOUT` so the child is killed and reported by command line
before the coarser per-test deadline takes down the whole worker.

**`KANON_TEST_PROCESS_KILL_GRACE`** (default: `5`) -- seconds a spawned
process group is given to exit after `SIGTERM` before the suite escalates to
`SIGKILL`. A process with a signal handler gets the chance to exit cleanly
rather than being killed outright.

**`KANON_SYNC_JOBS`** (test default: `1`) -- `tests/conftest.py` pins
this so `repo sync` runs in a single process. See `docs/configuration.md`
for what the variable does in production.

At the end of a session the controller process scans **only the process
groups the suite itself created** for `kanon` processes that outlived the
tests that spawned them. Each spawned command runs in its own process group,
so the whole subtree is addressable and a developer's unrelated `kanon`, a
second concurrent pytest session, or the shell running the tests can never be
mistaken for a leak.

Survivors get `SIGTERM`, then `SIGKILL` after `KANON_TEST_PROCESS_KILL_GRACE`
seconds. A kill that fails is reported rather than suppressed, and the session
exits with status 70: a leaked child means a subprocess helper is missing a
`timeout=`, so it is treated as a test failure rather than cleaned up quietly.

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

```text
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

```text
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
