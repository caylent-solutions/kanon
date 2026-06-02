# kanon Exit Codes

Canonical exit-code reference for the `kanon` CLI. All subcommands
follow the table below. Use this document in CI scripts to map exit
codes to pipeline actions.

## Canonical exit codes

| Code | Meaning | When emitted |
| ---- | ------- | ------------ |
| `0` | Success | Command completed successfully. |
| `1` | Runtime / usage error | Application-level failure (see below). |
| `2` | argparse error | Invalid command-line arguments. |
| `3` | Deprecated invocation | Invoked via a deprecated interface. |

**Future codes reserved.** Exit codes 4 and above are unassigned.
kanon will not emit them without a corresponding spec change.

### Code `0` -- success

The command ran and all work completed without error.

### Code `1` -- runtime / usage / resolution error

An application-level error occurred. Examples: filesystem error,
network error, resolution failure, validation failure, or malformed
input that the application detected after argument parsing succeeded.
Check stderr for an `ERROR:` line with the specific cause.

### Code `2` -- argparse usage error

Command-line arguments were invalid. argparse emits this when a
required positional is missing, an unknown flag is supplied, or a flag
value fails type conversion. Correct the invocation and retry.

### Code `3` -- deprecated invocation

The command was invoked via a deprecated interface. No work was
performed. The WARN message on stderr names the exact replacement
command. See
[docs/migration-bootstrap-to-add.md](migration-bootstrap-to-add.md).

## Per-subcommand reference

The table shows which codes each subcommand can emit.
`y` = the code is reachable. `--` = not reachable.

| Subcommand | `0` | `1` | `2` | `3` |
| ---------- | --- | --- | --- | --- |
| `kanon list` | y | y | y | -- |
| `kanon add` | y | y | y | -- |
| `kanon remove` | y | y | y | -- |
| `kanon outdated` | y | y | y | -- |
| `kanon why` | y | y | y | -- |
| `kanon catalog audit` | y | y | y | -- |
| `kanon validate xml` | y | y | y | -- |
| `kanon validate marketplace` | y | y | y | -- |
| `kanon validate metadata` | y | y | y | -- |
| `kanon install` | y | y | y | -- |
| `kanon doctor` | y | y | y | -- |
| `kanon bootstrap` | -- | -- | -- | y (all invocations) |
| `kanon bootstrap list` | -- | -- | -- | y (all invocations) |
| `kanon clean` | y | y | y | -- |
| `kanon completion` | y | y | y | -- |
| `kanon repo` | y | y | y | -- |

### Notes on `kanon clean`

`kanon clean` exits `0` on a successful teardown, `1` on a runtime error
(for example, a missing `.kanon` file or `KANON_MARKETPLACE_INSTALL=true`
with no `CLAUDE_MARKETPLACES_DIR` defined), and `2` on an argparse error.
The `--orphans` flag does not introduce a new exit code: it only changes
what cleanup is performed (additionally pruning orphaned-source
marketplaces from `~/.claude` before the normal teardown), not which codes
the command can emit.

### Notes on `kanon bootstrap` and `kanon bootstrap list`

`kanon bootstrap` was removed in a major release (a breaking change)
and is retained only as a uniform deprecation shim. **Every**
invocation -- any args, any flags, including `--help`/`-h`, unknown
flags, `kanon bootstrap list`, and bare `kanon bootstrap` -- prints a
deprecation message to stderr and exits with status `3` without
performing any work. There is no invocation that exits `0`, and no
argparse "unrecognized arguments" error: every flag is swallowed and
routed to the same message. The shim does not delegate, does not read
manifest-repo content, and does not touch the filesystem.

The message includes a per-invocation "CLOSEST REPLACEMENT" line:
`kanon bootstrap list` maps to
`kanon list --catalog-source <git-url>@<ref>`, and any other entry maps
to `kanon add <entry> --catalog-source <git-url>@<ref>`.

See [docs/migration-bootstrap-to-add.md](migration-bootstrap-to-add.md)
for the full migration guide.

## Using this table in CI

### Treat exit 3 as a hard failure

`kanon bootstrap` and `kanon bootstrap list` exit `3` to force
migration at the CI / script boundary. A script that calls either
command will fail immediately, which prevents stale tooling from
running silently.

If your CI pipeline surfaces exit `3`, update the script to use the
replacement command (`kanon add` or `kanon list`). Follow the migration
guide at
[docs/migration-bootstrap-to-add.md](migration-bootstrap-to-add.md).

Example -- GitHub Actions step that detects exit `3` and fails with a
diagnostic message:

```yaml
- name: Run kanon
  run: |
    set +e
    kanon bootstrap mypackage
    exit_code=$?
    if [ "$exit_code" -eq 3 ]; then
      echo "ERROR: 'kanon bootstrap' is deprecated." >&2
      echo "Replace with 'kanon add mypackage'." >&2
      echo "See docs/migration-bootstrap-to-add.md." >&2
      exit 1
    fi
    exit "$exit_code"
```

### Distinguish argparse errors from runtime errors

Exit `2` indicates the CLI was called with invalid arguments (wrong
flag name, missing required positional). Exit `1` indicates the
arguments were valid but the command failed at runtime (network error,
resolution error, file not found).

In shell scripts, check the exit code explicitly when you want to
separate "operator mistyped the command" from "the command ran but the
catalog was unavailable":

```bash
#!/usr/bin/env bash
set -euo pipefail

kanon list
rc=$?

case $rc in
  0) echo "OK" ;;
  1) echo "ERROR: runtime failure -- check stderr" >&2; exit 1 ;;
  2) echo "ERROR: bad arguments -- check syntax" >&2; exit 2 ;;
  3) echo "ERROR: deprecated command -- see migration guide" >&2; exit 1 ;;
  *) echo "ERROR: unexpected exit code $rc" >&2; exit 1 ;;
esac
```

### `kanon install` and lockfile drift

`kanon install` follows the npm-like reconcile model. Plain
`kanon install` reconciles `.kanon` against `.kanon.lock` (prune removed
sources, resolve added/changed sources, replay unchanged ones) and exits
`0`; ordinary `.kanon` edits do not produce a non-zero exit. To make the
lockfile authoritative in CI, run `kanon install --strict-lock`: it exits
`1` on any drift (an orphaned lock entry or a `kanon_hash` mismatch) and
never mutates the lockfile. `kanon install --refresh-lock` forces a full
rebuild and exits `0` on success. See
[docs/lockfile.md -- Install reconcile model](lockfile.md#install-reconcile-model).

### Gate on `kanon doctor` for workspace health checks

`kanon doctor` exits `1` when any health-check finding reaches
severity ERROR. Wire it as a required CI gate to catch stale lockfiles
and unreachable catalog sources before a build proceeds:

```yaml
- name: Workspace health check
  env:
    KANON_CATALOG_SOURCE: >-
      https://example.com/org/manifest-repo.git@main
  run: kanon doctor
```

Any non-zero exit blocks the pipeline and prints the failing findings
to stderr.

## See also

- [docs/list-and-add.md](list-and-add.md) -- `kanon list`, `kanon add`,
  `kanon remove`
- [docs/outdated-and-why.md](outdated-and-why.md) -- `kanon outdated`,
  `kanon why`
- [docs/cli/doctor.md](cli/doctor.md) -- `kanon doctor`
- [docs/cli/catalog-audit.md](cli/catalog-audit.md) --
  `kanon catalog audit`
- [docs/cli/validate.md](cli/validate.md) -- `kanon validate`
- [docs/lockfile.md](lockfile.md) -- lockfile format consumed by
  `kanon install`, `kanon doctor`, `kanon outdated`, `kanon why`
- [docs/migration-bootstrap-to-add.md](migration-bootstrap-to-add.md)
  -- full migration guide for `kanon bootstrap` users
