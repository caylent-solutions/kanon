# Security Model

kanon is designed around a strict trust model that keeps it safe to run in
regulated, multi-tenant CI/CD environments. This document describes the
security invariants enforced by the tooling and the automated tests that
verify them.

For the full specification see `spec/kanon-list-add-lock-features-spec.md`,
Section 3.6 (trust model) and Section 10 (CI enforcement).

## Provider-agnosticism

kanon is provider-agnostic (spec Section 3.6, invariant 1). This means:

- kanon NEVER calls provider HTTP APIs (`api.github.com`, `gitlab.com/api`,
  `bitbucket.org/!api`, `dev.azure.com/_apis`).
- kanon NEVER shells out to provider CLIs (`gh`, `glab`, `bb`, `tea`,
  `aws codecommit`, `az repos`).
- Every git interaction is via the `git` binary only.
- kanon NEVER prompts for credentials, caches them, or reads them from
  anywhere except by delegating to the operator's git client.

## Provider-agnosticism CI test

The provider-agnosticism invariant is enforced in CI by a tree-wide grep test:

- **Test file:** `tests/functional/test_provider_agnostic.py`
- **Allowlist file:** `tests/integration/provider_allowlist.txt`
- **Spec references:** Section 3.6 (trust model), Section 10 line 1023
  (CI grep test requirement), Section 12 acceptance item 20.

### How the test works

1. The test enumerates the tracked file set via `git ls-files` (local
   plumbing command -- no provider calls).
2. Files under `docs/`, `tests/fixtures/`, and `.git/` are always excluded
   (AC-FUNC-005 spec-mandated blanket exemptions, built into the test constant
   `_ALWAYS_ALLOWLISTED_PREFIXES`).
3. Additional path-specific exemptions are read from
   `tests/integration/provider_allowlist.txt` (see format below). Infrastructure
   paths such as `.devcontainer/`, `.github/`, `src/kanon_cli/repo/`, and
   `uv.lock` are declared here rather than in the built-in constant.
4. Each non-exempted tracked file is scanned line by line for:
   - Forbidden CLI tokens: `\bgh\b`, `\bglab\b`, `\bbb\b`, `\btea\b`,
     `aws codecommit`, `az repos`
   - Forbidden hostnames: `api.github.com`, `gitlab.com/api`,
     `bitbucket.org/!api`, `dev.azure.com/_apis`
5. On any match the test fails with the repo-relative file path, the
   1-based line number, the matched token, and a remediation hint.

### Allowlist format

`tests/integration/provider_allowlist.txt` lists files and directories that
are legitimately exempt from the scan (e.g., the vendored repo tool, CI
workflow files, lock files). Each non-comment, non-blank line must have the
shape:

```
<repo-relative-path>:<justification>
```

where `<justification>` is non-empty free text explaining why a human
reviewer accepted the exemption. Lines starting with `#` are comments. Blank
lines are ignored. A malformed line causes the test to fail with a
`ValueError` naming the line number.

Paths ending with `/` are treated as directory prefix exemptions -- every
tracked file whose path starts with that prefix is excluded from scanning.
This allows exempting an entire directory tree (e.g., `.github/`) with a
single entry rather than one entry per file.

Adding an entry to the allowlist requires a code review. Production source
files under `src/kanon_cli/` (excluding the vendored `src/kanon_cli/repo/`
subtree) MUST NOT appear in the allowlist; violations of the
provider-agnosticism invariant in production code must be fixed, not
exempted.

See `docs/contributing.md` for guidance on adding multi-provider parity test
fixtures and the workflow for updating the allowlist.

## Auth delegation

kanon detects authentication errors in `git` stderr output (via
`GIT_AUTH_ERROR_PATTERNS` in `src/kanon_cli/constants.py`) for retry-policy
purposes only. It does not prompt for credentials or cache them. All
credential resolution is delegated to the operator's git credential helper.

## HTTPS-by-default policy

kanon enforces an HTTPS-by-default trust model for remote URLs used in manifest
resolution (spec Section 3.6). Only the following URL schemes are accepted by
default:

- `https://` -- HTTPS (always accepted).
- `git@host:org/repo.git` -- SSH SCP shorthand (treated as HTTPS-equivalent).
- `ssh://git@host/org/repo` -- Explicit SSH protocol (treated as HTTPS-equivalent).

### SSH-equivalence

SSH URLs (`git@...` shorthand and `ssh://...`) are treated as equivalent to HTTPS
for trust purposes. Both delegate credential resolution to the operator's git
credential helper (SSH key agent or credential store) without kanon prompting for
or caching credentials.

### Non-HTTPS URL rejection

Plain HTTP (`http://`), `file://`, and all other URL schemes are rejected by the
`remote-url` catalog audit check (R002 ERROR) unless `KANON_ALLOW_INSECURE_REMOTES=1`
is set in the environment.

The opt-out variable is intended for local test fixtures and offline development
only. Production CI pipelines MUST NOT set `KANON_ALLOW_INSECURE_REMOTES=1`.

### Query-string and fragment prohibition

Fetch URLs containing a query string (`?`) or fragment (`#`) are always rejected
(R003 ERROR) regardless of the scheme and regardless of `KANON_ALLOW_INSECURE_REMOTES`.
URL canonicalization is undefined for such values (spec Section 4.8, E1-F2-S1-T1).

### Catalog audit enforcement

The HTTPS-by-default policy is enforced statically by `kanon catalog audit --check
remote-url`. See `docs/cli/catalog-audit.md` for the full `remote-url` check
reference including finding codes R001, R002, and R003.

## Subprocess safety

kanon does not use `eval()`, `exec()`, or dynamic code execution with
external input. All subprocess calls use list-form arguments (never
shell=True with user-supplied strings) and explicit `cwd` settings.
