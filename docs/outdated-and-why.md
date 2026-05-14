# kanon outdated and why

Operator-facing reference for two read-only inspection commands:
`kanon outdated` and `kanon why`.

For first-time setup see
[docs/setup-guide.md](setup-guide.md).
For the canonical environment-variable table see
[docs/configuration.md](configuration.md).
For the lockfile format that both commands read see
[docs/lockfile.md](lockfile.md).

---

## kanon outdated

Report installable upgrades per source.

### outdated -- Synopsis

```text
kanon outdated [--catalog-source <git-url>@<ref>]
               [--kanon-file <path>]
               [--lock-file <path>]
               [--format {table,json}]
               [--fail-on-upgrade]
               [--no-color]
```

### outdated -- How it works

`kanon outdated` resolves the catalog identified by `--catalog-source`
(or `KANON_CATALOG_SOURCE`), then reads every
`KANON_SOURCE_<name>_*` block from the `.kanon` file and compares the
currently-installed version against what the catalog now offers.

Steps:

1. Resolve the catalog source (required -- no lockfile fallback for
   this command; see [docs/configuration.md](configuration.md) for
   the `KANON_CATALOG_SOURCE` env var).
2. Read the `.kanon` file.
3. For each source block:
   - Determine the **current** resolved version from `.kanon.lock`
     when present; otherwise live-resolve against the catalog.
   - Determine **latest-matching-spec**: the highest version that
     still satisfies the PEP 440 constraint recorded in the source
     block.
   - Determine **latest-available**: the highest version that exists
     in the catalog regardless of the recorded constraint (shows the
     "relaxed upgrade" ceiling).
4. Emit one output row per source.

### outdated -- Flags

| Flag | Default | Description |
| ---- | ------- | ----------- |
| `--catalog-source <url>@<ref>` | env | Catalog source. |
| `--kanon-file <path>` | `./.kanon` | Declaration file. |
| `--lock-file <path>` | derived | Lockfile path. |
| `--format {table,json}` | `table` | Output format. |
| `--fail-on-upgrade` | off | Exit 1 on upgrade. |
| `--no-color` | auto | Disable ANSI color. |

Environment variable overrides: `--catalog-source` =
`KANON_CATALOG_SOURCE`, `--kanon-file` = `KANON_KANON_FILE`,
`--lock-file` = `KANON_LOCK_FILE`, `--format` =
`KANON_OUTDATED_FORMAT`. See
[docs/configuration.md](configuration.md) for details.

### outdated -- Exit codes

| Condition | Exit code |
| --------- | --------- |
| Completed normally, no upgrades available | `0` |
| Completed normally, upgrades available (default) | `0` |
| Upgrades available, `--fail-on-upgrade` passed | `1` |
| Catalog source not configured | `1` |
| `.kanon` file not found | `1` |
| Manifest repo contains zero PEP 440-parseable tags | `1` |
| Any unhandled error | `1` |

See [docs/exit-codes.md](exit-codes.md) for the full exit-code table.

The default exit-0 design follows the convention of `pip list
--outdated`, `npm outdated`, and `cargo outdated`: the report is
informational and does not block downstream pipeline steps unless the
operator opts in with `--fail-on-upgrade`.

### outdated -- Output format: table (default)

```text
$ kanon outdated \
    --catalog-source \
    https://example.com/org/manifest-repo.git@main

name       current  latest-spec  latest-avail  upgrade-type
---------  -------  -----------  ------------  ------------
package-a  1.2.0    1.2.1        2.0.0         patch/minor
package-b  3.0.0    3.0.0        3.1.0         --
package-c  main     a1b2c3d4e5f6 a1b2c3d4e5f6  drift
```

Column definitions:

| Column | Description |
| ------ | ----------- |
| `name` | Source name from `KANON_SOURCE_<name>_*`. |
| `current` | Version or SHA prefix currently in `.kanon.lock`. |
| `latest-spec` | Highest version satisfying the PEP 440 constraint. |
| `latest-avail` | Highest version ignoring the constraint. |
| `upgrade-type` | `patch/minor`, `major`, `drift`, or `--`. |

### outdated -- Branch-pinned source drift column

When a source's `REVISION` is a branch name (e.g., `main`, `develop`)
rather than a PEP 440 tag, version comparison is not applicable.
Instead:

- Both `latest-spec` and `latest-avail` display the current HEAD SHA
  of that branch, truncated to 12 characters.
- `upgrade-type` reads `drift` when the SHA in `.kanon.lock` differs
  from the branch HEAD.
- `upgrade-type` reads `--` when the locked SHA matches the branch
  HEAD.

Example -- `package-c` has drifted from the locked commit:

```text
name       current       latest-spec   latest-avail  upgrade-type
---------  ------------  ------------  ------------  ------------
package-c  a1b2c3d4e5f6  f6e5d4c3b2a1  f6e5d4c3b2a1  drift
```

Operators who want deterministic installs should switch branch-pinned
sources to tag-based pinning with a PEP 440 constraint.

### outdated -- Output format: --format json

```json
[
  {
    "name": "package-a",
    "current": "1.2.0",
    "latest_matching_spec": "1.2.1",
    "latest_available": "2.0.0",
    "upgrade_type": "patch/minor"
  },
  {
    "name": "package-b",
    "current": "3.0.0",
    "latest_matching_spec": "3.0.0",
    "latest_available": "3.1.0",
    "upgrade_type": "--"
  },
  {
    "name": "package-c",
    "current": "a1b2c3d4e5f6",
    "latest_matching_spec": "f6e5d4c3b2a1",
    "latest_available": "f6e5d4c3b2a1",
    "upgrade_type": "drift"
  }
]
```

### outdated -- Error scenarios

#### Missing catalog source

```text
ERROR: catalog source is not configured.
Set --catalog-source <url>@<ref> or export KANON_CATALOG_SOURCE=<url>@<ref>.
```

#### Manifest repo with no PEP 440 tags

When the manifest repo for a source contains only tags whose last path
component is not a valid PEP 440 version (e.g., `v1.0.0`,
`release-2024`), the `latest-spec` and `latest-avail` columns display
a loud error marker instead of a version, and the command exits
non-zero after printing all rows:

```text
name       current  latest-spec              latest-avail             upgrade-type
---------  -------  -----------------------  -----------------------  ------------
package-d  1.0.0    ERROR: no PEP 440 tags   ERROR: no PEP 440 tags   --

ERROR: one or more sources have no PEP 440-parseable tags.
Skipped tags for source 'package-d': v1.0.0, release-2024.
Ask the catalog author to publish PEP 440-compliant release tags,
or run:
  kanon catalog audit --check tag-format \
      --catalog-source \
      https://example.com/org/manifest-repo.git@main
```

---

## kanon why

Explain why a package, XML manifest, or source is present in the
resolved dependency tree.

### why -- Synopsis

```text
kanon why <name-or-url> [--kanon-file <path>]
          [--lock-file <path>]
          [--catalog-source <git-url>@<ref>]
          [--format {text,json}]
          [--no-color]
```

### why -- How it works

`kanon why` reads `.kanon` (and `.kanon.lock` when present) to build
the full resolved dependency tree, then traces every chain that ends at
the node identified by `<name-or-url>`. It resolves the tree from the
lockfile when available; a live catalog source is required only when no
lockfile exists.

### why -- Accepted argument shapes

The single positional argument is matched in the following precedence:

| Shape | Example |
| ----- | ------- |
| Project URL | `https://example.com/org/manifest-repo.git` |
| Transitive XML manifest path | `repo-specs/network/remote.xml` |
| Entry name | `package-a` |
| Source name | `package_a` |

Notes:

- Project URLs are canonicalized via `canonicalize_repo_url` before
  matching, so `http://` vs `https://` and trailing `.git` differences
  are normalized.
- Both the entry-name form (`package-a`) and the normalized source-name
  form (`package_a`) are accepted for top-level sources.

### why -- Chain walking

For every matching node, `kanon why` prints all resolution chains that
lead to it. A chain walks the `<include>` graph from a top-level source
entry down to the requested node:

```text
$ kanon why https://example.com/org/manifest-repo.git \
    --catalog-source \
    https://example.com/org/manifest-repo.git@main

package-a -> repo-specs/base.xml@a1b2c3d4e5f6 \
    -> repo-specs/network/remote.xml@b2c3d4e5f6a1 \
    -> https://example.com/org/manifest-repo.git@c3d4e5f6a1b2
```

Each node in the chain is annotated with its resolved SHA.

### why -- Cycle detection

If the transitive include graph contains a cycle (e.g., `A.xml`
includes `B.xml` which includes `A.xml`), `kanon why` exits with a
hard error before printing any output:

```text
ERROR: include cycle detected:
  repo-specs/base.xml -> repo-specs/ext.xml -> repo-specs/base.xml
Remove the cycle from the manifest repo and re-run.
```

### why -- Diamond deduplication

When two separate `<include>` paths both resolve to the same XML
manifest, the manifest is processed once. Both chains are shown in the
output, but the manifest itself is not duplicated in the resolution
tree:

```text
package-a -> repo-specs/base.xml@a1b2c3d4e5f6 \
    -> repo-specs/shared.xml@d4e5f6a1b2c3
package-a -> repo-specs/extra.xml@e5f6a1b2c3d4 \
    -> repo-specs/shared.xml@d4e5f6a1b2c3
```

### why -- Ambiguity behaviour

If the argument matches in more than one category simultaneously (for
example, a string that is both a valid source name and a valid XML
path), `kanon why` exits with a hard error listing all matching
interpretations:

```text
ERROR: 'shared' is ambiguous. It matches:
  source name : shared (KANON_SOURCE_shared_*)
  XML path    : repo-specs/shared.xml
Disambiguate by passing the full XML path or the exact source name.
```

### why -- Not-found behaviour

If the argument matches nothing in the resolved tree, `kanon why` exits
with a hard error. When candidates exist within edit distance 3
(Levenshtein), up to 3 closest matches are suggested:

```text
$ kanon why pacakge-a \
    --catalog-source \
    https://example.com/org/manifest-repo.git@main

ERROR: 'pacakge-a' not found in the resolved dependency tree.
Did you mean one of:
  package-a  (edit distance 2)
  package-b  (edit distance 3)
```

When no candidates are within the threshold, the error omits the
suggestion block:

```text
ERROR: 'zzz-unknown' not found in the resolved dependency tree.
```

The suggestion threshold and maximum number of suggestions are
configurable via environment variables; see
[docs/configuration.md](configuration.md) for
`KANON_WHY_SUGGEST_MAX_DISTANCE` and `KANON_WHY_SUGGEST_TOP_N`.

### why -- Flags

| Flag | Default | Description |
| ---- | ------- | ----------- |
| `--catalog-source <url>@<ref>` | env | Required when no lockfile. |
| `--kanon-file <path>` | `./.kanon` | Declaration file. |
| `--lock-file <path>` | derived | Lockfile path. |
| `--format {text,json}` | `text` | Output format. |
| `--no-color` | auto | Disable ANSI color. |

Environment variable overrides: `--catalog-source` =
`KANON_CATALOG_SOURCE`, `--kanon-file` = `KANON_KANON_FILE`,
`--lock-file` = `KANON_LOCK_FILE`, `--format` = `KANON_WHY_FORMAT`.
See [docs/configuration.md](configuration.md) for details.

### why -- Output format: --format json

With `--format json`, each chain is an array of node objects. The
top-level result is an array of chains:

```json
[
  [
    {
      "kind": "source",
      "name": "package-a",
      "ref": ">=1.0.0",
      "sha": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
      "url": "https://example.com/org/manifest-repo.git"
    },
    {
      "kind": "xml",
      "name": "repo-specs/base.xml",
      "ref": "main",
      "sha": "b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3",
      "url": "https://example.com/org/manifest-repo.git"
    },
    {
      "kind": "project",
      "name": "remote-lib",
      "ref": "==1.2.3",
      "sha": "c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4",
      "url": "https://example.com/org/manifest-repo.git"
    }
  ]
]
```

Node `kind` values:

| Value | Description |
| ----- | ----------- |
| `source` | A top-level `KANON_SOURCE_<name>_*` entry from `.kanon`. |
| `xml` | A transitive `<include>` XML manifest file. |
| `project` | A `<project>` package repo entry in an XML manifest. |

JSON indentation defaults to 2 spaces. Configure via
`KANON_WHY_JSON_INDENT` (see
[docs/configuration.md](configuration.md)).

---

## CI integration patterns

Both commands integrate naturally into automated pipelines. The typical
pattern is to run `kanon outdated --fail-on-upgrade` on a schedule and
take action (open a ticket, fail a PR gate) when upgrades are
available.

### GitHub Actions

The following workflow runs a nightly check and opens a GitHub issue
when upgrades are found. The `kanon outdated --format json` output is
captured for the issue body.

```yaml
name: dependency-drift

on:
  schedule:
    # Run at 06:00 UTC every day
    - cron: "0 6 * * *"
  workflow_dispatch: {}

jobs:
  check-outdated:
    runs-on: ubuntu-latest
    env:
      KANON_CATALOG_SOURCE: >-
        https://example.com/org/manifest-repo.git@main
    steps:
      - uses: actions/checkout@v4

      - name: Install kanon
        run: pip install kanon

      - name: Check for upgrades
        id: outdated
        # Exit 1 when upgrades are available; capture for issue body
        run: |
          set +e
          kanon outdated --fail-on-upgrade --format json \
            > outdated.json 2>&1
          echo "exit_code=$?" >> "$GITHUB_OUTPUT"

      - name: Open issue on drift
        if: steps.outdated.outputs.exit_code != '0'
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          gh issue create \
            --title "kanon: upgrades available ($(date -u +%Y-%m-%d))" \
            --body "$(cat outdated.json)" \
            --label "dependencies"
```

Key points:

- `KANON_CATALOG_SOURCE` is set as a job-level env var so all steps
  inherit it without repeating the flag.
- `set +e` prevents the shell from exiting before `$GITHUB_OUTPUT` is
  written.
- The `--format json` output is machine-readable and suitable as an
  issue or PR description body.

### Generic shell CI

For CI systems without a native YAML DSL (Jenkins, Buildkite custom
agents, Makefile targets), use a plain shell conditional:

```bash
#!/usr/bin/env bash
set -euo pipefail

export KANON_CATALOG_SOURCE="https://example.com/org/manifest-repo.git@main"

echo "Checking for kanon dependency upgrades..."

if ! kanon outdated --fail-on-upgrade; then
  echo "ERROR: kanon dependency upgrades are available." >&2
  echo "Run 'kanon outdated' for details, then update .kanon" >&2
  echo "and commit a refreshed lock." >&2
  exit 1
fi

echo "All kanon dependencies are up to date."
```

Adapt the error-handling block to your CI system's notification
mechanism (Slack webhook, PagerDuty alert, email, etc.).

PR gate variant: include the script as a required check in your CI
configuration. When `kanon outdated --fail-on-upgrade` exits 1, the
check fails and the PR cannot merge until the `.kanon` file is updated
and a new lock is committed.

---

## See also

- [docs/configuration.md](configuration.md) -- all environment
  variables controlling `kanon outdated` and `kanon why`
  (`KANON_OUTDATED_FORMAT`, `KANON_WHY_FORMAT`,
  `KANON_WHY_JSON_INDENT`, `KANON_WHY_SUGGEST_MAX_DISTANCE`,
  `KANON_WHY_SUGGEST_TOP_N`).
- [docs/list-and-add.md](list-and-add.md) -- the related read/write
  commands (`kanon list`, `kanon add`, `kanon remove`).
- [docs/exit-codes.md](exit-codes.md) -- the full exit-code table for
  all kanon commands.
- [docs/lockfile.md](lockfile.md) -- lockfile format and how both
  commands consume it.
- [docs/version-resolution.md](version-resolution.md) -- how PEP 440
  constraints are resolved against git tags.
