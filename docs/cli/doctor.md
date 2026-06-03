# kanon doctor

Run workspace health checks against the current project directory.

## Synopsis

```
kanon [--no-color] doctor [--kanon-file <path>] [--lock-file <path>] [--strict-drift] [--refresh-completion-cache] [--prune-cache] [--catalog-source <git-url>@<ref>]
```

## Description

`kanon doctor` inspects a kanon workspace and reports any inconsistencies
between the `.kanon` configuration file and the `.kanon.lock` lockfile. It
is read-only when invoked without `--refresh-completion-cache` or
`--prune-cache`: it reads files and queries remote repositories but does
not modify any local state.
With `--refresh-completion-cache`, it invalidates all files under
`${KANON_CACHE_DIR}/completion-cache/`.
With `--prune-cache`, it removes cache files whose atime is older than
`KANON_CACHE_PRUNE_AGE_DAYS` days and reports stale install-lock advisories.
Both flags are independent and may be combined.

Exit code is 0 when all checks pass (or when only info-level findings are
emitted). Exit code is 1 when any error-level finding is detected.

## Options

`--kanon-file <path>`
: Path to the `.kanon` configuration file. Defaults to `./.kanon`. The
  `KANON_KANON_FILE` environment variable is checked when this flag is not
  supplied; the CLI flag takes precedence when both are set.

`--lock-file <path>`
: Path to the `.kanon.lock` lockfile. Defaults to `<kanon-file>.lock`
  (e.g. `./.kanon.lock`). The `KANON_LOCK_FILE` environment variable is
  checked when this flag is not supplied.

`--strict-drift`
: Promote branch-drift findings from info-level to error-level. Without
  this flag, branch-drift is reported as an informational notice and the
  command exits 0. With this flag, any detected drift causes exit code 1.
  See subcheck 4 (Branch drift) below.

`--catalog-source <git-url>@<ref>`
: Override the catalog source for this invocation. Takes the form
  `<git-url>@<ref>` where `ref` is a branch, tag, or commit SHA.
  When supplied, this flag takes highest precedence in the effective
  catalog source resolution (see subcheck 6 below). Overrides the
  `KANON_CATALOG_SOURCE` environment variable and any lockfile
  `[catalog].source` value.

`--refresh-completion-cache`
: Subcheck 8: Invalidate all files under `${KANON_CACHE_DIR}/completion-cache/`,
  recreating the directory empty with mode `0700`. Reports an info finding
  with the count of files removed. This flag is independent of the health
  checks. Has no effect when `KANON_CACHE_DIR` is unset.

`--prune-cache`
: Subcheck 10: Remove files under `${KANON_CACHE_DIR}` whose last-access time
  is older than `KANON_CACHE_PRUNE_AGE_DAYS` days (default 30). Reports an
  info finding with the count and total byte size pruned. Also reports any
  stale `.kanon-data/.kanon-install.lock` files (mtime older than
  `KANON_DOCTOR_STALE_LOCK_AGE_HOURS` hours) as advisory findings -- doctor
  does NOT delete them. Has no effect on cache files when `KANON_CACHE_DIR`
  is unset; stale-lock scan always runs from the current working directory.

## Subchecks

`kanon doctor` runs the following consistency checks in order.

### Subcheck 1: .kanon / .kanon.lock consistency

Verifies that the `.kanon` file exists at the expected path and that a
`.kanon.lock` lockfile is present.

**Error when .kanon is absent (exit 1):**
```
ERROR: no kanon workspace in <cwd>: '.kanon' not found
  Remediation: Run 'kanon add ...' to create a .kanon file, or 'cd' to a
  directory that contains one.
```

**Info notice when .kanon.lock is absent (exit 0):**
```
INFO: No lockfile present; run `kanon install` to generate one.
  Remediation: kanon install
```

When `.kanon.lock` is absent, subchecks 2-5 and 11 are skipped; the command
exits 0 after emitting the info notice and running subchecks 6, 7, and 9.

### Subcheck 2: Hand-edit detection (kanon_hash)

Recomputes the `kanon_hash` digest over the current `.kanon` file and
compares it with the `kanon_hash` field stored in the lockfile. A mismatch
indicates the `.kanon` file was edited directly after the last
`kanon install` run.

**Error (exit 1):**
```
ERROR: kanon_hash mismatch: .kanon was hand-edited since the last 'kanon install'.
  Remediation: Run 'kanon install --refresh-lock' to rebuild the lockfile.
```

### Subcheck 3: Orphaned lock entries

For every source recorded in the lockfile, checks that the matching
`KANON_SOURCE_<name>_{URL,REVISION,PATH}` triple still exists in `.kanon`.
A source present in the lockfile but absent from `.kanon` is an orphan
(e.g. the source was removed from `.kanon` without re-running
`kanon install`).

**Error per orphan (exit 1):**
```
ERROR: orphan lock entry: source 'X' is in .kanon.lock but absent from .kanon
  Remediation: Run 'kanon install' to prune (or 'kanon install --strict-lock'
  to keep the lockfile authoritative).
```

### Subcheck 4: Branch drift

For every lockfile entry whose `revision_spec` resolves to a branch name
(not a SHA and not a `refs/...` ref), queries
`git ls-remote refs/heads/<branch>` against the source URL and compares
the current branch tip SHA with the locked SHA.

Without `--strict-drift`, drift is reported as an info notice (exit 0):
```
INFO: branch drift: source 'X' is locked to <old-sha> but 'main' is now at <new-sha>
  Remediation: Run 'kanon install --refresh-lock' to update the lockfile.
```

With `--strict-drift`, drift is reported as an error (exit 1):
```
ERROR: branch drift: source 'X' is locked to <old-sha> but 'main' is now at <new-sha>
  Remediation: Run 'kanon install --refresh-lock' to update the lockfile.
```

### Subcheck 5: Dangling SHA

For every lockfile entry whose `revision_spec` is a SHA (40 or 64 lowercase
hex characters), queries `git ls-remote <url>` and verifies the locked SHA
appears in the first column of the remote's ref list. A SHA that is not
found in any ref indicates the commit was force-pushed or pruned.

Branch-pinned sources are skipped by this check (they are handled by
subcheck 4 instead).

**Error (exit 1):**
```
ERROR: dangling SHA: <sha> is no longer reachable from <url>; the remote
may have force-pushed or pruned the commit.
  Remediation: Run 'kanon install --refresh-lock' to rebuild.
```

### Subcheck 6: Effective catalog source

Reports the effective catalog source and which configuration layer provided
it. This check always runs, regardless of whether `.kanon.lock` is present.

Resolution precedence (first non-empty wins):

1. `--catalog-source <git-url>@<ref>` CLI flag (highest priority).
2. `KANON_CATALOG_SOURCE` environment variable.
3. Lockfile `[catalog].source` field (only when `.kanon.lock` is present
   and its `catalog.source` field is non-empty).
4. None -- no catalog source is configured.

The provenance suffix is mandatory in every output path: it tells the
operator WHERE the effective value came from, not just what the value is.
This is how operators detect `KANON_CATALOG_SOURCE` leakage from a shell
profile into an unrelated workspace (see spec Section 3.6).

**Output printed to stdout:**

When a source is configured (examples for each precedence level):
```
Effective catalog source: https://example.com/org/catalog.git@main (from --catalog-source CLI flag)
Effective catalog source: https://example.com/org/catalog.git@main (from KANON_CATALOG_SOURCE env var)
Effective catalog source: https://example.com/org/catalog.git@main (from .kanon.lock [catalog].source)
```

When no source is configured (exit 0, but commands that need a catalog will fail):
```
Effective catalog source: (none configured); commands requiring a catalog source will fail.
```

**Example: detecting a leaked env var**

An operator has `KANON_CATALOG_SOURCE=https://corp.example.com/infra-catalog.git@main` in
their `.bashrc`, exported globally. They `cd` into an unrelated project and run
`kanon install`. To check before installing:

```
$ kanon doctor
...
Effective catalog source: https://corp.example.com/infra-catalog.git@main (from KANON_CATALOG_SOURCE env var)
```

The provenance suffix `(from KANON_CATALOG_SOURCE env var)` immediately reveals that
the catalog source comes from the environment, not from a local CLI flag or the
project's lockfile. The operator can then unset the variable before running any
side-effecting command:

```
$ unset KANON_CATALOG_SOURCE
$ kanon doctor
...
Effective catalog source: (none configured); commands requiring a catalog source will fail.
```

Without the provenance suffix, an operator reading only the URL would not know
whether it was intentional for this project or a stale variable from another session.

### Subcheck 8: Completion-cache invalidation (--refresh-completion-cache)

When `--refresh-completion-cache` is set and `KANON_CACHE_DIR` is configured,
all files under `${KANON_CACHE_DIR}/completion-cache/` are deleted and the
directory is recreated empty with mode `0700`. This invalidates any cached
completion data so the next completion invocation rebuilds the cache from
scratch.

This subcheck runs BEFORE subchecks 1-5, 7, 9, 10, and 11.

**Info finding after refresh:**
```
INFO: Completion cache refreshed: 3 file(s) removed from /home/user/.cache/kanon/completion-cache
```

When `KANON_CACHE_DIR` is not set, this subcheck is skipped silently.

### Subcheck 7: Completion errors report

Reads the most recent `KANON_COMPLETION_ERRORS_REPORT_LIMIT` lines (default 5)
from `${KANON_CACHE_DIR}/completion-errors.log`. This log is written by shell
completion callback failures (see E7 / `docs/shell-completions.md`).

`kanon doctor` only reads this log -- it does NOT modify, truncate, or rotate it.
If `KANON_CACHE_DIR` is not set, this subcheck is silently skipped.

**Info notice when the log is absent or empty:**
```
INFO: no completion errors recorded
```

**Warning when recent errors are present:**
```
WARN: Recent completion errors (5):
2026-01-01T12:00:00Z __complete_catalog_entries ValueError: empty response
2026-01-01T12:00:01Z __complete_source_names FileNotFoundError: .kanon not found
2026-01-01T12:00:02Z __complete_catalog_entries TimeoutError: git ls-remote timed out after 30s
2026-01-01T12:00:03Z __complete_source_names ValueError: malformed .kanon line 7
2026-01-01T12:00:04Z __complete_catalog_entries ConnectionError: name resolution failed
  Remediation: Inspect ${KANON_CACHE_DIR}/completion-errors.log for details.
```

When the log contains more than `KANON_COMPLETION_ERRORS_REPORT_LIMIT` lines,
only the most recent `KANON_COMPLETION_ERRORS_REPORT_LIMIT` lines are shown.
Malformed lines (no timestamp, unexpected format) are included verbatim.

### Subcheck 9: Completion-script staleness

When an operator has installed a static shell completion script (as opposed to
using the dynamic eval-time approach), this subcheck compares the on-disk
script's SHA-256 hash to a freshly generated script. If the hashes differ, the
operator's installed script is stale and should be regenerated.

Static completion script discovery uses the candidate paths from
`KANON_STATIC_COMPLETION_SEARCH_PATHS` (defined in `constants.py`). For each
path that exists on disk, the comparison is run independently. Multiple shells
(e.g., bash and zsh) may each have a stale script; one warning is emitted per
drifted script.

When no static completion scripts are installed at any candidate path, this
subcheck emits no finding (silent).
When a static script's hash matches the freshly generated output, no finding
is emitted for that shell.

**Warning when a bash script is stale (exit 0 -- warn is not error):**
```
WARN: Stale bash completion script: /home/user/.local/share/bash-completion/completions/kanon does not match the output of 'kanon completion bash'. Re-run 'kanon completion bash > /home/user/.local/share/bash-completion/completions/kanon' to update it.
  Remediation: kanon completion bash > /home/user/.local/share/bash-completion/completions/kanon
```

**Warning when a zsh script is stale:**
```
WARN: Stale zsh completion script: /home/user/.zsh/completions/_kanon does not match the output of 'kanon completion zsh'. Re-run 'kanon completion zsh > /home/user/.zsh/completions/_kanon' to update it.
  Remediation: kanon completion zsh > /home/user/.zsh/completions/_kanon
```

Multiple shells with stale scripts produce one warning per shell.

### Subcheck 11: Remote reachability sanity check

For every distinct remote URL recorded in the lockfile, runs
`git ls-remote --exit-code <url> HEAD` (subject to `KANON_RESOLVE_TIMEOUT`
and the retry policy). URLs are deduplicated using `canonicalize_repo_url`
before the check, so SSH and HTTPS forms of the same repository are checked
exactly once.

This check runs ONLY when `.kanon.lock` is present. If the lockfile is absent,
subcheck 1 short-circuits and subcheck 11 is skipped.

**Difference from subcheck 5 (dangling SHA):**

| | Subcheck 5 (dangling SHA) | Subcheck 11 (remote reachability) |
|---|---|---|
| What it checks | Whether a specific locked SHA is still reachable at the remote | Whether the remote URL itself is reachable at all |
| What triggers it | Non-zero `git ls-remote` exit OR SHA not in any ref's first column | Non-zero `git ls-remote --exit-code <url> HEAD` for any reason |
| Severity | **error** (exit 1) | **warning** (exit 0) |
| Retries | Subject to `KANON_GIT_RETRY_COUNT` / `KANON_GIT_RETRY_DELAY` | Same retry policy; auth-error patterns skip retries |

Remote-reachability failures are deliberately warnings rather than errors.
Network connectivity is transient: a `kanon doctor` run that fails with exit 1
because the operator's network is down is not useful as a triage tool. The
warning surfaces the diagnostic -- URL, exit code, first line of stderr -- so
the operator can investigate (missing SSH key, unconfigured credential helper,
network outage, repository moved) without blocking a workspace check.

**Warning when a remote is unreachable (exit 0):**
```
WARN: remote unreachable: https://example.com/org/repo (exit code 128); stderr: repository not found
  Remediation: Check network access and git credentials for https://example.com/org/repo. See docs/git-auth-setup.md for SSH key and credential helper setup.
```

The warning includes:
- The canonicalized URL (`.git` suffix and user-info stripped).
- The exit code returned by `git ls-remote --exit-code`.
- The first line of stderr, truncated at `KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS`
  characters (default 160) to keep output bounded.
- A remediation hint referencing `docs/git-auth-setup.md`.

**Auth errors (e.g., missing SSH key):**

Auth-error patterns matching `GIT_AUTH_ERROR_PATTERNS` (e.g., `Permission denied`,
`Authentication`) skip the retry policy to avoid credential lockouts, but still
produce the same warning finding. The operator should configure their SSH agent
or credential helper before re-running:

```
WARN: remote unreachable: https://github.com/org/repo (exit code 128); stderr: Permission denied (publickey).
  Remediation: Check network access and git credentials for https://github.com/org/repo. See docs/git-auth-setup.md for SSH key and credential helper setup.
```

**All remotes reachable:** No finding is emitted.

### Subcheck 10: Cache pruning and stale-lock advisory (--prune-cache)

When `--prune-cache` is set, two actions occur:

**10a -- Cache prune:** All files under `${KANON_CACHE_DIR}` (recursively)
whose last-access time (`atime`) is older than `KANON_CACHE_PRUNE_AGE_DAYS`
days are deleted. The number of deleted files and their combined byte size are
reported as an info finding.

**10b -- Stale install-lock advisory:** The working directory is scanned
(recursively, up to `KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH` levels) for
`.kanon-data/.kanon-install.lock` files whose mtime is older than
`KANON_DOCTOR_STALE_LOCK_AGE_HOURS` hours. Each such file is reported as
an advisory info finding. Doctor does NOT delete these files; `fcntl.flock`
self-cleans on process exit, so a leftover file on disk is harmless and does
not block subsequent installs.

This subcheck runs BEFORE subchecks 1-5, 7, 9, and 11, and AFTER subcheck 8
when both flags are combined.

**Info finding after pruning 2 files totalling 4096 bytes:**
```
INFO: Cache pruned: 2 file(s) removed (4096 bytes) with atime older than 30 days
```

**Advisory finding for a stale install lock:**
```
INFO: Advisory: stale install lock found at /path/to/.kanon-data/.kanon-install.lock (mtime older than 1h). fcntl.flock self-cleans on process exit; this file is harmless.
```

When `KANON_CACHE_DIR` is not set, only the stale-lock scan runs; no cache
files are pruned.

**Combining both flags:**
```
kanon doctor --refresh-completion-cache --prune-cache
```
Refresh runs first (subcheck 8), then prune runs (subcheck 10). Both findings
are emitted. Health checks (subchecks 1-5, 6, 7, 9, 11) always run after.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `KANON_KANON_FILE` | `./.kanon` | Path to the `.kanon` configuration file |
| `KANON_LOCK_FILE` | `<kanon-file>.lock` | Path to the `.kanon.lock` lockfile |
| `KANON_CATALOG_SOURCE` | (none) | Catalog source as `<git-url>@<ref>`; overridden by `--catalog-source` CLI flag |
| `KANON_RESOLVE_TIMEOUT` | `30` | Timeout in seconds for each `git ls-remote` call |
| `KANON_GIT_RETRY_COUNT` | `3` | Maximum number of `git ls-remote` attempts |
| `KANON_GIT_RETRY_DELAY` | `1` | Seconds to wait between retry attempts |
| `KANON_CACHE_DIR` | (none) | Directory where cache files are stored; when unset, subchecks 7, 8, and 10's cache prune are skipped |
| `KANON_COMPLETION_ERRORS_REPORT_LIMIT` | `5` | Maximum number of recent completion-error log lines to display in subcheck 7 |
| `KANON_CACHE_PRUNE_AGE_DAYS` | `30` | Files older than this many days (by atime) are removed by `--prune-cache` (subcheck 10) |
| `KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH` | `4` | Maximum directory depth for the stale install-lock scan in `--prune-cache` (subcheck 10) |
| `KANON_DOCTOR_STALE_LOCK_AGE_HOURS` | `1` | Minimum lock file age in hours to qualify as stale in the advisory scan (subcheck 10) |
| `KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS` | `160` | Maximum characters from the first line of `git ls-remote` stderr included in a remote-reachability warning (subcheck 11) |

## Exit Codes

| Code | Meaning |
|---|---|
| `0` | All checks passed (or only info-level findings) |
| `1` | One or more error-level findings detected |

## Examples

Run all health checks against the default `.kanon` file:
```
kanon doctor
```

Promote branch-drift findings to errors:
```
kanon doctor --strict-drift
```

Use a custom kanon file location:
```
kanon doctor --kanon-file /path/to/my/.kanon
```

Run checks with an explicit lock file path:
```
kanon doctor --kanon-file /path/to/.kanon --lock-file /path/to/.kanon.lock
```

Check which catalog source is active (subcheck 6) and override with a specific one:
```
kanon doctor --catalog-source https://example.com/org/catalog.git@main
```

Detect a leaked `KANON_CATALOG_SOURCE` env var (look for the provenance suffix in stdout):
```
kanon doctor
# Expected output when env var is set:
# Effective catalog source: https://corp.example.com/catalog.git@main (from KANON_CATALOG_SOURCE env var)
```

Invalidate the completion cache (removes all files under `${KANON_CACHE_DIR}/completion-cache/`):
```
kanon doctor --refresh-completion-cache
# Expected stderr output:
# INFO: Completion cache refreshed: 5 file(s) removed from /home/user/.cache/kanon/completion-cache
```

Remove stale cache files older than 30 days and check for stale install locks:
```
kanon doctor --prune-cache
# Expected stderr output:
# INFO: Cache pruned: 3 file(s) removed (24576 bytes) with atime older than 30 days
```

Run both refresh and prune together:
```
kanon doctor --refresh-completion-cache --prune-cache
```

## See Also

- `kanon install` -- Install all sources defined in `.kanon`
- `kanon install --refresh-lock` -- Rebuild the lockfile from the current `.kanon`
- `docs/lockfile.md` -- Lockfile schema reference
- `docs/configuration.md` -- Full configuration reference
