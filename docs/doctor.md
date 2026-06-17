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
10. Stale cache entries are optionally pruned (`--prune-cache`).
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

## Subchecks

### Subcheck 1 -- .kanon file presence

#### What it inspects

Whether a `.kanon` file exists in the workspace (or at the path given by
`--kanon-file` / `KANON_KANON_FILE`). When `.kanon` is present but
`.kanon.lock` is absent, an info-level notice is printed and subchecks 2-5
and 11 are skipped. Subchecks 6-10 still run.

#### Pass message

```text
[OK]  .kanon present
```

When the lockfile is absent:

```text
[INFO] No lockfile present; run `kanon install` to generate one.
```

#### Fail message

```text
ERROR: no kanon workspace in <cwd>: '.kanon' not found
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

#### Pass message

```text
[OK]  .kanon consistent with lockfile (kanon_hash match)
```

#### Fail message

```text
ERROR: .kanon has been modified since the lockfile was written.
  Expected kanon_hash: <hash-from-lockfile>
  Actual   kanon_hash: <hash-of-current-kanon-file>
  Run `kanon install --refresh-lock` to regenerate the lockfile, or
  revert .kanon to its locked state.
```

#### Zero-source `.kanon` (`NO_SOURCES`)

Recomputing the `kanon_hash` re-parses `.kanon`. When the file declares no
sources (no `KANON_SOURCE_<name>_*` triples), the recompute cannot proceed
and doctor reports a structured `NO_SOURCES` error finding instead of leaking
a traceback, then exits non-zero:

```text
ERROR: no sources declared in .kanon; add one with 'kanon add <entry>'
  Run 'kanon add <entry>' to declare at least one source.
```

#### Reproducer

```bash
# create a workspace and generate a lockfile
kanon install --catalog-source https://example.com/org/manifest-repo.git@main

# hand-edit .kanon (add or remove a source line)
echo "# hand edit" >> .kanon

# now doctor reports the hash mismatch
kanon doctor --catalog-source https://example.com/org/manifest-repo.git@main
# exits 1 with the error above
```

---

### Subcheck 3 -- orphaned lock entries

#### What it inspects

Whether `.kanon.lock` contains entries for sources that have since been
removed from `.kanon`. An orphaned entry means the lockfile is out of sync;
the workspace may contain stale clones. This check is skipped when no
lockfile is present.

#### Pass message

```text
[OK]  no orphaned lock entries
```

#### Fail message

```text
ERROR: orphaned lock entries detected (sources removed from .kanon but
  still present in .kanon.lock):
    - <source-name>
  Run `kanon install --refresh-lock` to regenerate the lockfile.
```

#### Reproducer

```bash
# after initial install, remove a source from .kanon
kanon remove <source-name>

# without running kanon install, run doctor
kanon doctor --catalog-source https://example.com/org/manifest-repo.git@main
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

#### Pass message

```text
[OK]  no branch drift detected
```

When drift is detected (default, non-strict mode):

```text
[INFO] branch drift detected for <source-name>:
  locked SHA:  <sha-from-lock>
  branch tip:  <current-remote-sha>
  branch:      refs/heads/<branch>
  Use `kanon install --refresh-lock-source <source-name>` to accept the
  new SHA, or `kanon install --refresh-lock` to refresh all sources.
```

#### Fail message (--strict-drift only)

```text
ERROR: branch drift detected for <source-name> (--strict-drift):
  locked SHA:  <sha-from-lock>
  branch tip:  <current-remote-sha>
  branch:      refs/heads/<branch>
  Run `kanon install --refresh-lock-source <source-name>` to accept
  the drift, or revert to the locked SHA.
```

#### Reproducer

```bash
# run doctor in strict mode to treat drift as an error
kanon doctor --strict-drift \
  --catalog-source https://example.com/org/manifest-repo.git@main
```

---

### Subcheck 5 -- locked SHA reachability

#### What it inspects

For every locked SHA in `.kanon.lock`, whether that SHA is still reachable
from its declared remote via `git ls-remote --exit-code <url> <sha>`. A
dangling SHA means the remote history was force-pushed or the ref was deleted.
This check is skipped when no lockfile is present.

#### Pass message

```text
[OK]  all locked SHAs reachable
```

#### Fail message

```text
ERROR: locked SHA is no longer reachable from its remote:
  source:  <source-name>
  remote:  <url>
  SHA:     <sha>
  The remote may have been force-pushed. Run `kanon install --refresh-lock`
  to re-resolve from scratch (requires a catalog source).
```

#### Reproducer

```bash
# force-push a branch that kanon has locked, then run doctor
kanon doctor --catalog-source https://example.com/org/manifest-repo.git@main
# exits 1 with the dangling-SHA error above
```

---

### Subcheck 6 -- effective catalog source

#### What it inspects

The effective catalog source resolved for this workspace. See the
[Effective catalog source](#effective-catalog-source) section for the full
precedence chain and security rationale.

This check always runs (even when no lockfile is present).

#### Pass message

When a source is resolved:

```text
[OK]  effective catalog source: https://example.com/org/manifest-repo.git@main
        (resolved from: KANON_CATALOG_SOURCES)
```

The parenthetical names the resolution tier: `--catalog-source flag`,
`KANON_CATALOG_SOURCES env var`, or `lockfile [catalog].source`.

When no source is configured:

```text
[WARN] no catalog source configured; commands requiring one will fail.
  Set KANON_CATALOG_SOURCES or pass --catalog-source <git-url>@<ref>.
```

#### Fail message

No exit-1 condition. Absence of a catalog source is a warning, not an error,
because some subchecks (1-5) can still pass without one.

#### Reproducer

```bash
# confirm which catalog source is active without side effects
kanon doctor --no-color 2>&1 | grep "effective catalog source"
```

---

### Subcheck 7 -- recent completion errors

#### What it inspects

The N most recent structured errors written to
`${KANON_HOME}/completion-errors.log` by the completion engine. Default
N is `5`. These errors are non-blocking at the shell but are surfaced here so
operators can diagnose completion failures.

This check always runs.

#### Pass message

```text
[OK]  no recent completion errors
```

When errors are present:

```text
[WARN] 2 recent completion error(s):
  2026-05-01T12:00:00Z  __complete_kanon_add: git ls-remote timed out
                        (KANON_CATALOG_SOURCES=https://example.com/org/manifest-repo.git@main)
  2026-04-30T18:00:00Z  __complete_kanon_search: no catalog source configured
  Run `kanon doctor --refresh-completion-cache` to clear and rebuild the cache.
```

#### Fail message

No exit-1 condition. Completion errors are advisory.

#### Reproducer

```bash
# view completion errors without triggering any cache mutations
kanon doctor --no-color 2>&1 | grep -A 10 "completion error"
```

---

### Subcheck 8 -- completion cache refresh (--refresh-completion-cache)

#### What it inspects

When `--refresh-completion-cache` is passed, this subcheck invalidates the
entire completion cache before any other checks run. It is an escape hatch for
when the cache is corrupt or contains stale entries that cannot be pruned by
the age-based `--prune-cache` path.

Without `--refresh-completion-cache`, this subcheck is a no-op and no message
is printed.

#### Pass message

```text
[OK]  completion cache invalidated and rebuilt
```

#### Fail message

```text
ERROR: failed to invalidate completion cache at <KANON_HOME>:
  <OS error details>
```

#### Reproducer

```bash
# force a full cache rebuild
kanon doctor --refresh-completion-cache \
  --catalog-source https://example.com/org/manifest-repo.git@main
```

---

### Subcheck 9 -- completion script staleness

#### What it inspects

When a static completion script is installed on disk (e.g., at
`~/.local/share/bash-completion/completions/kanon` or
`~/.zsh/completion/_kanon`), this subcheck compares the on-disk script's hash
to a fresh `kanon completion <shell>` invocation. A mismatch means the
installed script is stale relative to the currently-installed version of
kanon.

This check always runs but only emits output when a static script is found.

#### Pass message

```text
[OK]  completion script up to date (bash)
```

#### Fail message

```text
[WARN] completion script is stale (bash):
  installed: <path-to-static-script>
  To update:
    kanon completion bash > ~/.local/share/bash-completion/completions/kanon
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

When `--prune-cache` is passed, removes `${KANON_HOME}` entries whose
`accessed_at` timestamp is older than `KANON_CACHE_PRUNE_AGE_DAYS` days
(default `30`). Also reports any stale `.kanon-data/.kanon-install.lock` files
that are held by no live process (advisory only; `kanon doctor` does not
delete them because `fcntl.flock` releases automatically on process exit, so
a leftover file on disk is harmless).

Without `--prune-cache`, this subcheck is a no-op and no message is printed.

#### Pass message

```text
[OK]  cache pruned: 3 entries removed (14 entries retained)
```

When no entries qualify:

```text
[OK]  cache pruned: 0 entries removed (14 entries retained)
```

#### Fail message

```text
ERROR: failed to prune cache at <KANON_HOME>:
  <OS error details>
```

#### Reproducer

```bash
# prune cache entries older than 30 days (default)
kanon doctor --prune-cache

# prune more aggressively: set KANON_CACHE_PRUNE_AGE_DAYS=7
KANON_CACHE_PRUNE_AGE_DAYS=7 kanon doctor --prune-cache
```

---

### Subcheck 11 -- remote reachability

#### What it inspects

For every distinct remote URL in `.kanon.lock`, runs
`git ls-remote --exit-code <url> HEAD` (subject to `KANON_RESOLVE_TIMEOUT`
and the `KANON_GIT_RETRY_COUNT` retry policy). Errors are **non-blocking**:
they surface as actionable diagnostics but do NOT cause exit code `1`. This
helps catch missing SSH keys or unconfigured credential helpers without
bypassing the operator's git client.

This check is skipped when no lockfile is present.

#### Pass message

```text
[OK]  all remotes reachable (2 checked)
```

#### Fail message (non-blocking advisory)

```text
[WARN] remote unreachable (network issues are transient -- this is advisory):
  url: git@github.com:org/manifest-repo.git
  error: git@github.com: Permission denied (publickey).
  Check your SSH key configuration. See docs/git-auth-setup.md.
```

#### Reproducer

```bash
# test reachability for all remotes in the lockfile
kanon doctor --catalog-source https://example.com/org/manifest-repo.git@main

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

**Side effect:** causes exit code `1` on the first drift finding. Does not
modify `.kanon`, `.kanon.lock`, or any workspace file.

```bash
kanon doctor --strict-drift \
  --catalog-source https://example.com/org/manifest-repo.git@main
```

Use `--strict-drift` in CI pipelines where you want to enforce that all
branch-pinned dependencies are refreshed before merging.

---

### --prune-cache

Triggers subcheck 10: removes cache entries in `${KANON_HOME}` whose
`accessed_at` timestamp is older than `KANON_CACHE_PRUNE_AGE_DAYS` days
(default `30`). Pruning is opt-in; without this flag the cache is never
modified by `kanon doctor`.

**Default behaviour:** cache is not touched.

**Side effect:** may delete files under `${KANON_HOME}`. Reports each
removed entry to stdout. Also reports stale `.kanon-install.lock` files
(advisory; does not delete them).

```bash
kanon doctor --prune-cache

# shorten the retention window via environment variable
KANON_CACHE_PRUNE_AGE_DAYS=7 kanon doctor --prune-cache
```

For the `KANON_CACHE_PRUNE_AGE_DAYS` variable see
[docs/configuration.md](configuration.md).

---

### --refresh-completion-cache

Triggers subcheck 8: invalidates the entire completion cache before any
other subchecks run. Use this when the cache is corrupt or contains stale
entries that `--prune-cache` does not remove (because their `accessed_at`
timestamp is recent but their content is wrong).

**Default behaviour:** completion cache is not modified.

**Side effect:** deletes and rebuilds the completion cache. Acquires the
`.kanon-data/.kanon-install.lock` lock during cache mutation (the same lock
used by `kanon install`) to prevent concurrent mutations.

```bash
kanon doctor --refresh-completion-cache \
  --catalog-source https://example.com/org/manifest-repo.git@main
```

---

## Effective catalog source

`kanon doctor` resolves the effective catalog source using the following
precedence (highest wins):

1. `--catalog-source <git-url>@<ref>` CLI flag.
2. `KANON_CATALOG_SOURCES` environment variable.
3. `[catalog].source` field in `.kanon.lock` (lockfile fallback -- see below).
4. None configured -- prints a warning; no exit-1 from this condition alone.

The resolved value is always printed (subcheck 6) so the operator can
verify which catalog source is active before running side-effecting commands.

### Why this matters: shell-profile leakage

`KANON_CATALOG_SOURCES` is commonly set in shell profiles (`~/.bashrc`,
`~/.zshrc`, `~/.profile`) to avoid typing `--catalog-source` on every
invocation. This convenience creates a risk: if you `cd` into an unrelated
workspace and run `kanon install`, the shell-profile value silently overrides
whatever catalog source is appropriate for that workspace.

`kanon doctor` surfaces the effective source explicitly so you can catch this
class of mistake before it causes a silent mismatch:

```text
[OK]  effective catalog source: https://example.com/org/manifest-repo.git@main
        (resolved from: KANON_CATALOG_SOURCES)
```

If the printed source does not match the one your workspace expects, unset
`KANON_CATALOG_SOURCES` and pass `--catalog-source` explicitly.

### Lockfile fallback

`kanon doctor` (and `kanon install`) are the only two commands that fall back
to the lockfile's `[catalog].source` field when neither `--catalog-source` nor
`KANON_CATALOG_SOURCES` is set. All other commands (`kanon search`, `kanon add`,
`kanon outdated`, `kanon why`, `kanon catalog audit`) hard-error on a missing
catalog source.

The lockfile fallback applies only when the lockfile is present and its
`kanon_hash` is consistent with the current `.kanon` file. If the lockfile is
absent or inconsistent, `kanon doctor` reports "no catalog source configured"
and proceeds with whatever subchecks do not require a source.

```bash
# lockfile fallback in action: no env var, no CLI flag, but .kanon.lock present
kanon doctor
# [OK]  effective catalog source: https://example.com/org/manifest-repo.git@main
#         (resolved from: lockfile [catalog].source)
```

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
- Cache-prune failure (subcheck 10).

Branch-drift notices (subcheck 4 without `--strict-drift`), catalog-source
absence (subcheck 6), completion errors (subcheck 7), completion-script
staleness (subcheck 9), and remote-reachability warnings (subcheck 11) are
advisory and do not cause exit code `1`.

For the full exit-code matrix across all subcommands see
[docs/exit-codes.md](exit-codes.md).

---

## Worked examples

### All green

```text
$ kanon doctor --catalog-source https://example.com/org/manifest-repo.git@main

[OK]  .kanon present
[OK]  .kanon consistent with lockfile (kanon_hash match)
[OK]  no orphaned lock entries
[OK]  no branch drift detected
[OK]  all locked SHAs reachable
[OK]  effective catalog source: https://example.com/org/manifest-repo.git@main
        (resolved from: --catalog-source flag)
[OK]  no recent completion errors
[OK]  completion script up to date (bash)
[OK]  all remotes reachable (1 checked)
```

Exit code: `0`

---

### Failure: .kanon not found

```text
$ kanon doctor
ERROR: no kanon workspace in /home/user/project: '.kanon' not found
```

Exit code: `1`

**Fix:** create a `.kanon` file or `cd` into a directory that contains one.

---

### Failure: kanon_hash mismatch (hand-edited .kanon)

```text
$ kanon doctor --catalog-source https://example.com/org/manifest-repo.git@main

[OK]  .kanon present
ERROR: .kanon has been modified since the lockfile was written.
  Expected kanon_hash: a1b2c3d4e5f6...
  Actual   kanon_hash: 9f8e7d6c5b4a...
  Run `kanon install --refresh-lock` to regenerate the lockfile, or
  revert .kanon to its locked state.
```

Exit code: `1`

**Fix:** run `kanon install --refresh-lock` to regenerate the lockfile after
intentional edits, or revert `.kanon` if the edit was accidental.

---

### Failure: orphaned lock entry

```text
$ kanon doctor --catalog-source https://example.com/org/manifest-repo.git@main

[OK]  .kanon present
[OK]  .kanon consistent with lockfile (kanon_hash match)
ERROR: orphaned lock entries detected (sources removed from .kanon but
  still present in .kanon.lock):
    - my-removed-source
  Run `kanon install --refresh-lock` to regenerate the lockfile.
```

Exit code: `1`

**Fix:** run `kanon install --refresh-lock`.

---

### Info: branch drift (non-strict mode)

```text
$ kanon doctor --catalog-source https://example.com/org/manifest-repo.git@main

[OK]  .kanon present
[OK]  .kanon consistent with lockfile (kanon_hash match)
[OK]  no orphaned lock entries
[INFO] branch drift detected for my-source:
  locked SHA:  abc123def456...
  branch tip:  fed987cba654...
  branch:      refs/heads/main
  Use `kanon install --refresh-lock-source my-source` to accept the
  new SHA, or `kanon install --refresh-lock` to refresh all sources.
[OK]  all locked SHAs reachable
...
```

Exit code: `0` (drift is advisory without `--strict-drift`)

---

### Failure: branch drift with --strict-drift

```text
$ kanon doctor --strict-drift \
    --catalog-source https://example.com/org/manifest-repo.git@main

...
ERROR: branch drift detected for my-source (--strict-drift):
  locked SHA:  abc123def456...
  branch tip:  fed987cba654...
  branch:      refs/heads/main
  Run `kanon install --refresh-lock-source my-source` to accept
  the drift, or revert to the locked SHA.
```

Exit code: `1`

---

### Failure: dangling locked SHA

```text
$ kanon doctor --catalog-source https://example.com/org/manifest-repo.git@main

...
ERROR: locked SHA is no longer reachable from its remote:
  source:  my-source
  remote:  https://example.com/org/manifest-repo.git
  SHA:     deadbeef1234...
  The remote may have been force-pushed. Run `kanon install --refresh-lock`
  to re-resolve from scratch (requires a catalog source).
```

Exit code: `1`

---

### Warning: no catalog source configured

```text
$ kanon doctor

[OK]  .kanon present
[OK]  .kanon consistent with lockfile (kanon_hash match)
[OK]  no orphaned lock entries
...
[WARN] no catalog source configured; commands requiring one will fail.
  Set KANON_CATALOG_SOURCES or pass --catalog-source <git-url>@<ref>.
...
```

Exit code: `0` (warning only, unless another subcheck produced an error)

---

### Warning: remote unreachable (advisory)

```text
$ kanon doctor --catalog-source https://example.com/org/manifest-repo.git@main

...
[WARN] remote unreachable (network issues are transient -- this is advisory):
  url: git@github.com:org/manifest-repo.git
  error: git@github.com: Permission denied (publickey).
  Check your SSH key configuration. See docs/git-auth-setup.md.
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
