# kanon Exit Codes

Canonical exit-code reference for the `kanon` CLI. All subcommands
follow the table below. Use this document in CI scripts to map exit
codes to pipeline actions.

## Canonical exit codes

| Code | Meaning | When emitted |
| ---- | ------- | ------------ |
| `0` | Success | Command completed successfully. |
| `1` | Runtime / usage error | Application-level failure (see below). |
| `2` | argparse error | Invalid command-line arguments (including a removed/unknown subcommand). |

**No deprecated-invocation exit code.** kanon 3.0.0 removed `kanon
bootstrap` and `kanon list` outright; neither is a registered subcommand,
so invoking them produces an argparse `invalid choice` usage error (exit
`2`) rather than a dedicated deprecation code. The `EXIT_CODE_DEPRECATED`
(`3`) constant remains defined in the source but is not emitted by any
command.

**Future codes reserved.** Exit codes 3 and above are unassigned.
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
required positional is missing, an unknown flag is supplied, a flag
value fails type conversion, or a removed/unknown subcommand (such as
`kanon bootstrap` or `kanon list`) is named. Correct the invocation and
retry. For removed commands, see
[docs/migration-to-add.md](migration-to-add.md).

## Per-subcommand reference

The table shows which codes each subcommand can emit.
`y` = the code is reachable. `--` = not reachable.

| Subcommand | `0` | `1` | `2` |
| ---------- | --- | --- | --- |
| `kanon search` | y | y | y |
| `kanon add` | y | y | y |
| `kanon remove` | y | y | y |
| `kanon outdated` | y | y | y |
| `kanon why` | y | y | y |
| `kanon catalog audit` | y | y | y |
| `kanon validate xml` | y | y | y |
| `kanon validate marketplace` | y | y | y |
| `kanon validate metadata` | y | y | y |
| `kanon validate lockfile` | y | y | y |
| `kanon install` | y | y | y |
| `kanon doctor` | y | y | y |
| `kanon marketplace` | y | y | y |
| `kanon clean` | y | y | y |
| `kanon completion` | y | y | y |
| `kanon repo` | y | y | y |

Removed commands (`kanon bootstrap`, `kanon list`) are not registered
subcommands; invoking them yields the argparse `invalid choice` usage
error (exit `2`). See the note below.

### Notes on `kanon clean`

`kanon clean` exits `0` on a successful teardown, `1` on a runtime error
(for example, a missing `.kanon` file, or a dependency with
`KANON_SOURCE_<alias>_MARKETPLACE=true` while no `CLAUDE_MARKETPLACES_DIR`
is defined), and `2` on an argparse error.
The `--orphans` flag does not introduce a new exit code: it only changes
what cleanup is performed (additionally pruning orphaned-source
marketplaces from `~/.claude` before the normal teardown), not which codes
the command can emit.

### Notes on removed commands (`kanon bootstrap`, `kanon list`)

`kanon bootstrap` and `kanon list` were **removed in kanon 3.0.0** (a
breaking change). There is **no compatibility shim**: neither is a
registered subcommand. Every invocation -- any args, any flags,
including `--help`/`-h`, `kanon bootstrap list`, and bare `kanon
bootstrap` -- fails at argument parsing with an argparse `invalid choice`
usage error and exits with status `2`. No work is performed; the
filesystem and manifest repo are never read.

`kanon list` was renamed to `kanon search`; `kanon bootstrap`'s
catalog-discovery and add functionality is replaced by `kanon search` +
`kanon add` + `kanon install`.

See [docs/migration-to-add.md](migration-to-add.md)
for the full migration guide.

## Using this table in CI

### Removed commands fail with exit 2

`kanon bootstrap` and `kanon list` are no longer registered subcommands,
so a script that calls either fails immediately with the argparse
`invalid choice` usage error (exit `2`). This forces migration at the CI
/ script boundary and prevents stale tooling from running silently.

If your CI pipeline surfaces this error, update the script to use the
replacement command (`kanon add` / `kanon search`). Follow the migration
guide at
[docs/migration-to-add.md](migration-to-add.md).

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

kanon search
rc=$?

case $rc in
  0) echo "OK" ;;
  1) echo "ERROR: runtime failure -- check stderr" >&2; exit 1 ;;
  2) echo "ERROR: bad arguments (or removed command) -- check syntax" >&2; exit 2 ;;
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
    KANON_CATALOG_SOURCES: >-
      https://example.com/org/manifest-repo.git@main
  run: kanon doctor
```

Any non-zero exit blocks the pipeline and prints the failing findings
to stderr.

## See also

- [docs/list-and-add.md](list-and-add.md) -- `kanon search`, `kanon add`,
  `kanon remove`
- [docs/outdated-and-why.md](outdated-and-why.md) -- `kanon outdated`,
  `kanon why`
- [docs/cli/doctor.md](cli/doctor.md) -- `kanon doctor`
- [docs/cli/catalog-audit.md](cli/catalog-audit.md) --
  `kanon catalog audit`
- [docs/cli/validate.md](cli/validate.md) -- `kanon validate`
- [docs/lockfile.md](lockfile.md) -- lockfile format consumed by
  `kanon install`, `kanon doctor`, `kanon outdated`, `kanon why`
- [docs/migration-to-add.md](migration-to-add.md)
  -- full migration guide for `kanon bootstrap` users
