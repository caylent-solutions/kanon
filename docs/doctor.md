# kanon doctor

Workspace health check command. `kanon doctor` inspects the consistency of
`.kanon`, `.kanon.lock`, the install workspace, the completion cache, and the
effective catalog source. Run it before side-effecting commands to catch
stale lockfiles, catalog-source mismatches, and completion-cache drift.

## What kanon doctor does

`kanon doctor` runs eleven sequential subchecks against the current workspace:

1. `.kanon` exists and the lockfile (if present) is consistent with it.
2. The `.kanon` file has not been hand-edited since the lockfile was written
   (`kanon_hash` comparison).
3. No orphaned entries exist in `.kanon.lock` (sources removed from `.kanon`
   but still present in the lock).
4. Branch-pinned dependencies have not drifted from the locked SHA.
5. Every locked SHA is still reachable from its remote.
6. The effective catalog source is resolved and printed for operator
   verification.
7. Recent completion errors are surfaced from the completion-error log.
8. The completion cache is optionally refreshed (`--refresh-completion-cache`).
9. Installed static completion scripts are checked for staleness.
10. Stale cache files are optionally pruned by last-access time
    (`--prune-cache`).
11. Remote reachability is verified for every distinct URL in the lockfile.

Exit code `0` means all subchecks passed. Exit code `1` means at least one
error-severity finding was reported. See [docs/exit-codes.md](exit-codes.md)
for the full exit-code matrix.

**Synopsis:**

```text
kanon doctor [--kanon-file <path>] [--lock-file <path>]
             [--catalog-source <git-url>@<ref>]
             [--refresh-completion-cache] [--strict-drift]
             [--prune-cache] [--no-color]
```

**Output format:** detailed findings are written to **stderr** prefixed with
`ERROR:`, `WARN:`, or `INFO:` (followed by a `Remediation:` line when the
finding carries one). On **stdout**, subchecks 1-4 emit a one-line structured
summary -- `[ok] <subcheck>` when they pass or `[fail] <subcheck>` when they
fail -- and subcheck 6 prints the plain `Effective catalog source: ...` line.
Subchecks 5, 7, 9, and 11 emit only the stderr findings above (no `[ok]`
summary line). The examples below show the messages each subcheck produces.

## Subchecks

### Subcheck 1 -- .kanon file presence

#### What it inspects

Whether a `.kanon` file exists in the workspace (or at the path given by
`--kanon-file` / `KANON_KANON_FILE`). When `.kanon` is present but
`.kanon.lock` is absent, an info-level notice is printed and subchecks 2-5
and 11 are skipped. Subchecks 6-10 still run.

#### Pass message

When `.kanon` (and a consistent lockfile) are present, the merged
presence/`kanon_hash` subcheck reports its `[ok]` summary on stdout:

```text
[ok] kanon_hash consistency
```

When the lockfile is absent, an info finding is written to stderr and
subchecks 2-5 and 11 are skipped (subchecks 6, 7, 9 still run):

```text
INFO: No lockfile present; run `kanon install` to generate one.
  Remediation: kanon install
```

#### Fail message

When `.kanon` is missing, an error finding is written to stderr and a `[fail]`
summary to stdout:

```text
ERROR: no kanon workspace in <cwd>: '.kanon' not found
  Remediation: Run 'kanon add ...' to create a .kanon file, or 'cd' to a directory that contains one.
[fail] kanon_hash consistency
```

#### Reproducer

```bash
# from a directory without a .kanon file
kanon doctor
# exits 1 with the error above
```

---

### Subcheck 2 -- kanon_hash consistency

#### What it inspects

Whether the current `.kanon` file matches the `kanon_hash` recorded in
`.kanon.lock`. A mismatch means `.kanon` was hand-edited after the lockfile
was written. This check is skipped when no lockfile is present.

Presence and `kanon_hash` consistency share one structured summary,
`[ok] kanon_hash consistency` (shown under subcheck 1). A mismatch flips that
summary to `[fail] kanon_hash consistency` and writes the error finding below.

#### Fail message

```text
ERROR: kanon_hash mismatch: .kanon was hand-edited since the last 'kanon install'.
  Remediation: Run 'kanon install --refresh-lock' to rebuild the lockfile.
[fail] kanon_hash consistency
```

#### Zero-source `.kanon` (`NO_SOURCES`)

Recomputing the `kanon_hash` re-parses `.kanon`. When the file declares no
sources (no `KANON_SOURCE_<alias>_*` blocks), the recompute cannot proceed
and doctor reports a structured `NO_SOURCES` error finding instead of leaking
a traceback, then exits non-zero:

```text
ERROR: no sources declared in .kanon; add one with 'kanon add <entry>'
  Remediation: Run 'kanon add <entry>' to declare at least one source.
[fail] kanon_hash consistency
```

#### Reproducer

```bash
# create a workspace and generate a lockfile
kanon install

# hand-edit .kanon (add or remove a source line)
echo "# hand edit" >> .kanon

# now doctor reports the hash mismatch
kanon doctor
# exits 1 with the error above
```

---

### Subcheck 3 -- orphaned lock entries

#### What it inspects

Whether `.kanon.lock` contains entries for sources that have since been
removed from `.kanon`. An orphaned entry means the lockfile is out of sync;
the workspace may contain stale clones. This check is skipped when no
lockfile is present.

For every source recorded in the lockfile, doctor checks that the matching
alias-keyed `KANON_SOURCE_<alias>_{URL,REF,PATH,NAME}` block still exists in
`.kanon` (matched by alias; optional per-dependency env-var lines do not affect
presence). One error finding is emitted per orphan.

#### Pass message

```text
[ok] no orphaned lock entries
```

#### Fail message

One stderr finding per orphan, plus the `[fail]` summary:

```text
ERROR: orphan lock entry: source '<source-name>' is in .kanon.lock but absent from .kanon
  Remediation: Run 'kanon install' to prune (or 'kanon install --strict-lock' to keep the lockfile authoritative).
[fail] no orphaned lock entries
```

#### Reproducer

```bash
# after initial install, remove a source from .kanon
kanon remove <source-name>

# without running kanon install, run doctor
kanon doctor
# exits 1 with the orphaned-entry error above
```

---

### Subcheck 4 -- branch drift

#### What it inspects

For each branch-pinned dependency in `.kanon.lock`, whether the branch tip
on the remote has advanced beyond the locked SHA. Each branch-pinned source
costs one `git ls-remote refs/heads/<branch>` call, bounded by
`KANON_RESOLVE_TIMEOUT` (default `30`s) and subject to the
`KANON_GIT_RETRY_COUNT` retry policy.

By default this is an **info-level notice** (not an error). Passing
`--strict-drift` upgrades it to an error and causes exit code `1`.

This check is skipped when no lockfile is present.

A source is treated as branch-pinned when its lockfile `ref_spec` is not a SHA
and not a `refs/...` ref. SHA-pinned sources are skipped (handled by subcheck 5).

#### Pass message

```text
[ok] no branch drift
```

When drift is detected (default, non-strict mode), an info finding is written
to stderr; because it is not error-level, the structured summary stays `[ok]`
and the command still exits 0:

```text
INFO: branch drift: source '<source-name>' is locked to <locked-sha-12> but '<branch>' is now at <tip-sha-12>
  Remediation: Run 'kanon install --refresh-lock' to update the lockfile.
[ok] no branch drift
```

#### Fail message (--strict-drift only)

With `--strict-drift`, the same finding is promoted to error-level, flipping the
summary to `[fail]` and the exit code to 1:

```text
ERROR: branch drift: source '<source-name>' is locked to <locked-sha-12> but '<branch>' is now at <tip-sha-12>
  Remediation: Run 'kanon install --refresh-lock' to update the lockfile.
[fail] no branch drift
```

#### Reproducer

```bash
# run doctor in strict mode to treat drift as an error
kanon doctor --strict-drift
```

---

### Subcheck 5 -- locked SHA reachability

#### What it inspects

For every SHA-pinned lockfile entry, whether that SHA is still reachable from
its declared remote. Doctor runs `git ls-remote <url>` (no ref filter) and
searches the first column of the output for the locked SHA, because
`git ls-remote --exit-code <url> <sha>` matches ref *names*, not SHA values.
A dangling SHA means the remote history was force-pushed or the ref was
deleted. Branch-pinned sources are skipped (handled by subcheck 4). This check
is skipped when no lockfile is present.

This subcheck emits only the stderr finding below; it does not print an
`[ok]` summary line.

#### Pass message

No finding is emitted when every locked SHA is reachable.

#### Fail message

```text
ERROR: dangling SHA: <sha> is no longer reachable from <url>; the remote may have force-pushed or pruned the commit.
  Remediation: Run 'kanon install --refresh-lock' to rebuild.
```

#### Reproducer

```bash
# force-push a branch that kanon has locked, then run doctor
kanon doctor
# exits 1 with the dangling-SHA error above
```

---

### Subcheck 6 -- effective catalog source

#### What it inspects

The effective catalog source resolved for this workspace. See the
[Effective catalog source](#effective-catalog-source) section for the full
precedence chain and security rationale.

This check always runs (even when no lockfile is present).

#### Output

The effective catalog source is printed as a plain line on stdout (no severity
prefix), with a mandatory provenance suffix naming where the value came from.

When a source is resolved:

```text
Effective catalog source: https://example.com/org/manifest-repo.git@main (from KANON_CATALOG_SOURCES env var)
```

The provenance suffix is one of `(from --catalog-source CLI flag)` or
`(from KANON_CATALOG_SOURCES env var)`. The lockfile never participates:
schema v4 removed the `[catalog]` block.

When `KANON_CATALOG_SOURCES` configures more than one source:

```text
KANON_CATALOG_SOURCES configures 2 catalog sources (https://example.com/org/a.git@main, https://example.com/org/b.git@main) (from KANON_CATALOG_SOURCES env var); single-source commands require --catalog-source to select one.
```

When no source is configured:

```text
Effective catalog source: (none configured); commands requiring a catalog source will fail.
```

#### Fail message

No exit-1 condition. Absence of a catalog source is reported as an informational
line, not an error, because some subchecks (1-5) can still pass without one.

#### Reproducer

```bash
# confirm which catalog source is active without side effects
# (the line is printed to stdout)
kanon doctor --no-color | grep "Effective catalog source"
```

---

### Subcheck 7 -- recent completion errors

#### What it inspects

The most recent `KANON_COMPLETION_ERRORS_REPORT_LIMIT` (default `5`) lines from
`${KANON_HOME}/cache/completion-errors.log`, written by shell completion
callback failures. These errors are non-blocking at the shell but are surfaced
here so operators can diagnose completion failures.

This check always runs. The cache directory resolves from `KANON_HOME` (the
`--home` / `--store-dir` flag, then the env var, then the `~/.kanon` default).
This subcheck emits only the stderr finding below; it does not print an `[ok]`
summary line.

#### Pass message

When the log is absent or empty:

```text
INFO: no completion errors recorded
```

When errors are present (warn level; does not affect the exit code):

```text
WARN: Recent completion errors (2):
2026-05-01T12:00:00Z __complete_catalog_entries ValueError: empty response
2026-04-30T18:00:00Z __complete_source_names FileNotFoundError: .kanon not found
  Remediation: Inspect ${KANON_HOME}/cache/completion-errors.log for details.
```

#### Fail message

No exit-1 condition. Completion errors are advisory.

#### Reproducer

```bash
# view completion errors without triggering any cache mutations
kanon doctor --no-color 2>&1 | grep -A 10 "completion errors"
```

---

### Subcheck 8 -- completion cache refresh (--refresh-completion-cache)

#### What it inspects

When `--refresh-completion-cache` is passed, this subcheck invalidates the
entire completion cache before any other checks run. It is an escape hatch for
when the cache is corrupt or contains stale entries that cannot be pruned by
the age-based `--prune-cache` path.

It removes all files under `${KANON_HOME}/cache/completion-cache/` and recreates
the directory empty with mode `0700`. Without `--refresh-completion-cache`, this
subcheck is a no-op and no message is printed.

#### Pass message

```text
INFO: Completion cache refreshed: 3 file(s) removed from /home/user/.kanon/cache/completion-cache
```

#### Fail message

On an OS error the command prints to stderr and exits 1:

```text
ERROR: Failed to refresh completion cache: <OS error details>
```

#### Reproducer

```bash
# force a full cache rebuild
kanon doctor --refresh-completion-cache
```

---

### Subcheck 9 -- completion script staleness

#### What it inspects

When a static completion script is installed at one of the candidate paths in
`KANON_STATIC_COMPLETION_SEARCH_PATHS` (e.g.
`~/.local/share/bash-completion/completions/kanon` for bash or
`~/.zsh/completions/_kanon` for zsh), this subcheck compares the on-disk
script's SHA-256 hash to a freshly generated `kanon completion <shell>` script.
A mismatch means the installed script is stale relative to the running version
of kanon. One warning is emitted per drifted script.

This check always runs but only emits output when a static script is found and
its hash differs. This subcheck emits only the stderr finding below; it does
not print an `[ok]` summary line.

#### Pass message

No finding is emitted when no static script is installed, or when an installed
script matches the freshly generated output.

#### Fail message

```text
WARN: Stale bash completion script: /home/user/.local/share/bash-completion/completions/kanon does not match the output of 'kanon completion bash'. Re-run 'kanon completion bash > /home/user/.local/share/bash-completion/completions/kanon' to update it.
  Remediation: kanon completion bash > /home/user/.local/share/bash-completion/completions/kanon
```

#### Reproducer

```bash
# install the completion script, upgrade kanon, then run doctor
kanon completion bash > ~/.local/share/bash-completion/completions/kanon
pip install --upgrade kanon-cli
kanon doctor
# warns that the static script needs regeneration
```

---

### Subcheck 10 -- cache pruning (--prune-cache)

#### What it inspects

When `--prune-cache` is passed, removes files under `${KANON_HOME}/cache`
(recursively) whose last-access time (`atime`) is older than
`KANON_CACHE_PRUNE_AGE_DAYS` days (default `30`). It also scans the current
working directory (up to `KANON_DOCTOR_STALE_LOCK_SCAN_MAX_DEPTH` levels) for
stale `.kanon-data/.kanon-install.lock` files older than
`KANON_DOCTOR_STALE_LOCK_AGE_HOURS` hours and reports them as advisory info
findings only -- `kanon doctor` does not delete them because `fcntl.flock`
releases automatically on process exit, so a leftover file on disk is harmless.

Without `--prune-cache`, this subcheck is a no-op and no message is printed.
This subcheck emits only the stderr info findings below; it does not print an
`[ok]` summary line.

#### Pass message

An info finding reports the count and total byte size pruned (always emitted,
even when zero files qualify):

```text
INFO: Cache pruned: 3 file(s) removed (24576 bytes) with atime older than 30 days
```

Each stale install lock found produces an advisory info finding:

```text
INFO: Advisory: stale install lock found at /path/to/.kanon-data/.kanon-install.lock (mtime older than 1h). fcntl.flock self-cleans on process exit; this file is harmless.
```

#### Fail message

There is no exit-1 path for the prune itself; individual unstattable or
unremovable files are skipped with a `WARN:` line and do not change the exit
code.

#### Reproducer

```bash
# prune cache files older than 30 days (default)
kanon doctor --prune-cache

# prune more aggressively: set KANON_CACHE_PRUNE_AGE_DAYS=7
KANON_CACHE_PRUNE_AGE_DAYS=7 kanon doctor --prune-cache
```

---

### Subcheck 11 -- remote reachability

#### What it inspects

For every distinct remote URL in `.kanon.lock`, runs
`git ls-remote --exit-code <url> HEAD` (subject to `KANON_RESOLVE_TIMEOUT`
and the `KANON_GIT_RETRY_COUNT` retry policy). URLs are deduplicated via
`canonicalize_repo_url`, so SSH and HTTPS forms of the same repository are
checked once. Errors are **non-blocking**: they surface as actionable
diagnostics but do NOT cause exit code `1`. Auth-error patterns (e.g.
`Permission denied`, `Authentication`) skip the retry policy to avoid
credential lockouts but still produce the same warning.

This check is skipped when no lockfile is present. It emits only the stderr
finding below; it does not print an `[ok]` summary line.

#### Pass message

No finding is emitted when every remote is reachable.

#### Fail message (non-blocking advisory)

```text
WARN: remote unreachable: https://github.com/org/manifest-repo (exit code 128); stderr: Permission denied (publickey).
  Remediation: Check network access and git credentials for https://github.com/org/manifest-repo. See docs/git-auth-setup.md for SSH key and credential helper setup.
```

The stderr preview is truncated at `KANON_DOCTOR_REMOTE_STDERR_PREVIEW_CHARS`
characters (default 160).

#### Reproducer

```bash
# test reachability for all remotes in the lockfile
kanon doctor

# with SSH key missing, subcheck 11 warns but doctor still exits 0
# (unless another subcheck produced an error)
```

---

## Flags

### --strict-drift

Upgrades branch-drift notices (subcheck 4) from INFO level to ERROR level,
causing `kanon doctor` to exit `1` when any branch-pinned dependency has
drifted from its locked SHA.

**Default behaviour:** branch drift is reported as an info-level notice;
`kanon doctor` continues and exits `0` if no other error-level finding is
present.

**Side effect:** causes exit code `1` when any drift finding is present. Does
not modify `.kanon`, `.kanon.lock`, or any workspace file.

```bash
kanon doctor --strict-drift
```

Use `--strict-drift` in CI pipelines where you want to enforce that all
branch-pinned dependencies are refreshed before merging.

---

### --prune-cache

Triggers subcheck 10: removes files under `${KANON_HOME}/cache` whose
last-access time (`atime`) is older than `KANON_CACHE_PRUNE_AGE_DAYS` days
(default `30`). Pruning is opt-in; without this flag the cache is never
modified by `kanon doctor`.

**Default behaviour:** cache is not touched.

**Side effect:** may delete files under `${KANON_HOME}/cache`. Reports an info
finding with the count and total bytes pruned. Also reports stale
`.kanon-install.lock` files in the working directory (advisory; does not delete
them).

```bash
kanon doctor --prune-cache

# shorten the retention window via environment variable
KANON_CACHE_PRUNE_AGE_DAYS=7 kanon doctor --prune-cache
```

For the `KANON_CACHE_PRUNE_AGE_DAYS` variable see
[docs/configuration.md](configuration.md).

---

### --refresh-completion-cache

Triggers subcheck 8: invalidates the completion cache before any other
subchecks run. Use this when the cache is corrupt or contains stale entries
that `--prune-cache` does not remove (because their last-access time is recent
but their content is wrong).

**Default behaviour:** completion cache is not modified.

**Side effect:** deletes all files under `${KANON_HOME}/cache/completion-cache/`
and recreates the directory empty with mode `0700`.

```bash
kanon doctor --refresh-completion-cache
```

---

## Effective catalog source

`kanon doctor` resolves the effective catalog source using the following
precedence (highest wins):

1. `--catalog-source <git-url>@<ref>` CLI flag.
2. The single source configured in the `KANON_CATALOG_SOURCES` environment
   variable. `KANON_CATALOG_SOURCES` (plural) is a newline-separated list; when
   it configures exactly one entry that entry is the effective value, and when
   it configures several the finding reports the ambiguity.
3. None configured -- prints an informational line; no exit-1 from this
   condition alone.

Schema v4 removed the lockfile `[catalog]` block, so the lockfile does NOT
participate in catalog-source resolution. The resolved value is always printed
(subcheck 6) so the operator can verify which catalog source is active before
running catalog-dependent commands (`kanon add`, `kanon search`, `kanon
outdated`, `kanon why`). `kanon install` is hermetic and does not consult a
catalog source at all.

### Why this matters: shell-profile leakage

`KANON_CATALOG_SOURCES` is commonly set in shell profiles (`~/.bashrc`,
`~/.zshrc`, `~/.profile`) to avoid typing `--catalog-source` on every
invocation. This convenience creates a risk: if you `cd` into an unrelated
workspace and run a catalog-dependent command, the shell-profile value silently
overrides whatever catalog source is appropriate for that workspace.

`kanon doctor` surfaces the effective source explicitly so you can catch this
class of mistake before it causes a silent mismatch:

```text
Effective catalog source: https://example.com/org/manifest-repo.git@main (from KANON_CATALOG_SOURCES env var)
```

If the printed source does not match the one your workspace expects, unset
`KANON_CATALOG_SOURCES` and pass `--catalog-source` explicitly.

For the security rationale behind this design see
[docs/security-model.md](security-model.md) and spec Section 3.6.

---

## Exit codes

| Exit code | Meaning |
| --------- | ------- |
| `0` | All subchecks passed (or produced only INFO/WARN findings). |
| `1` | At least one subcheck produced an ERROR-level finding. |
| `2` | Invalid command-line arguments (argparse error). |

`kanon doctor` exits `1` on any of the following:

- `.kanon` not found (subcheck 1).
- `kanon_hash` mismatch (subcheck 2).
- Orphaned lock entries (subcheck 3).
- Branch drift when `--strict-drift` is active (subcheck 4).
- Dangling locked SHA (subcheck 5).
- Completion-cache invalidation failure (subcheck 8).

Branch-drift notices (subcheck 4 without `--strict-drift`), catalog-source
absence (subcheck 6), completion errors (subcheck 7), completion-script
staleness (subcheck 9), cache pruning (subcheck 10), and remote-reachability
warnings (subcheck 11) are advisory and do not cause exit code `1`.

For the full exit-code matrix across all subcommands see
[docs/exit-codes.md](exit-codes.md).

---

## Worked examples

The `[ok]` / `[fail]` summary lines below are written to stdout; the `INFO:` /
`WARN:` / `ERROR:` findings are written to stderr. The examples interleave both
streams as a terminal would show them.

### All green

```text
$ kanon doctor --catalog-source https://example.com/org/manifest-repo.git@main

[ok] kanon_hash consistency
[ok] no orphaned lock entries
[ok] no branch drift
Effective catalog source: https://example.com/org/manifest-repo.git@main (from --catalog-source CLI flag)
INFO: no completion errors recorded
```

Exit code: `0`

Subchecks 5, 9, and 11 emit no output when they pass, so a clean run is sparse.

---

### Failure: .kanon not found

```text
$ kanon doctor
ERROR: no kanon workspace in /home/user/project: '.kanon' not found
  Remediation: Run 'kanon add ...' to create a .kanon file, or 'cd' to a directory that contains one.
[fail] kanon_hash consistency
```

Exit code: `1`

**Fix:** create a `.kanon` file or `cd` into a directory that contains one.

---

### Failure: kanon_hash mismatch (hand-edited .kanon)

```text
$ kanon doctor

ERROR: kanon_hash mismatch: .kanon was hand-edited since the last 'kanon install'.
  Remediation: Run 'kanon install --refresh-lock' to rebuild the lockfile.
[fail] kanon_hash consistency
```

Exit code: `1`

**Fix:** run `kanon install --refresh-lock` to regenerate the lockfile after
intentional edits, or revert `.kanon` if the edit was accidental.

---

### Failure: orphaned lock entry

```text
$ kanon doctor

[ok] kanon_hash consistency
ERROR: orphan lock entry: source 'my-removed-source' is in .kanon.lock but absent from .kanon
  Remediation: Run 'kanon install' to prune (or 'kanon install --strict-lock' to keep the lockfile authoritative).
[fail] no orphaned lock entries
```

Exit code: `1`

**Fix:** run `kanon install` to prune the orphaned entry.

---

### Info: branch drift (non-strict mode)

```text
$ kanon doctor

[ok] kanon_hash consistency
[ok] no orphaned lock entries
INFO: branch drift: source 'my-source' is locked to abc123def456 but 'main' is now at fed987cba654
  Remediation: Run 'kanon install --refresh-lock' to update the lockfile.
[ok] no branch drift
Effective catalog source: https://example.com/org/manifest-repo.git@main (from --catalog-source CLI flag)
INFO: no completion errors recorded
```

Exit code: `0` (drift is advisory without `--strict-drift`)

---

### Failure: branch drift with --strict-drift

```text
$ kanon doctor --strict-drift

[ok] kanon_hash consistency
[ok] no orphaned lock entries
ERROR: branch drift: source 'my-source' is locked to abc123def456 but 'main' is now at fed987cba654
  Remediation: Run 'kanon install --refresh-lock' to update the lockfile.
[fail] no branch drift
```

Exit code: `1`

---

### Failure: dangling locked SHA

```text
$ kanon doctor

[ok] kanon_hash consistency
[ok] no orphaned lock entries
[ok] no branch drift
ERROR: dangling SHA: deadbeef1234deadbeef1234deadbeef1234dead is no longer reachable from https://example.com/org/manifest-repo.git; the remote may have force-pushed or pruned the commit.
  Remediation: Run 'kanon install --refresh-lock' to rebuild.
```

Exit code: `1`

---

### Info: no catalog source configured

```text
$ kanon doctor

[ok] kanon_hash consistency
[ok] no orphaned lock entries
[ok] no branch drift
Effective catalog source: (none configured); commands requiring a catalog source will fail.
INFO: no completion errors recorded
```

Exit code: `0` (an unconfigured catalog source does not, by itself, fail doctor)

---

### Warning: remote unreachable (advisory)

```text
$ kanon doctor

[ok] kanon_hash consistency
[ok] no orphaned lock entries
[ok] no branch drift
WARN: remote unreachable: https://github.com/org/manifest-repo (exit code 128); stderr: Permission denied (publickey).
  Remediation: Check network access and git credentials for https://github.com/org/manifest-repo. See docs/git-auth-setup.md for SSH key and credential helper setup.
Effective catalog source: https://example.com/org/manifest-repo.git@main (from --catalog-source CLI flag)
INFO: no completion errors recorded
```

Exit code: `0` (reachability errors are advisory)

---

## See also

- [docs/exit-codes.md](exit-codes.md) -- exit-code matrix for all
  subcommands, including `kanon doctor`
- [docs/configuration.md](configuration.md) -- all environment variables
  (`KANON_CATALOG_SOURCES`, `KANON_HOME`, `KANON_CACHE_PRUNE_AGE_DAYS`,
  `KANON_RESOLVE_TIMEOUT`, `KANON_GIT_RETRY_COUNT`, `KANON_KANON_FILE`,
  `KANON_LOCK_FILE`)
- [docs/lockfile.md](lockfile.md) -- `.kanon.lock` format, `kanon_hash`
  semantics, and lockfile-to-install-workspace mapping
- [docs/security-model.md](security-model.md) -- trust model and effective
  catalog source rationale (spec Section 3.6)
- [docs/git-auth-setup.md](git-auth-setup.md) -- SSH and credential-helper
  configuration for git remotes
- [docs/troubleshooting.md](troubleshooting.md) -- common errors with
  reproducer and fix, including completion-cache corruption
