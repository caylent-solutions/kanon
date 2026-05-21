# Kanon Troubleshooting Guide

This guide covers common errors and how to diagnose and resolve them.
Each scenario includes a reproducer command and a fix.

---

## 1. Unquoted PEP 440 Specs

### Symptom

The shell interprets `>` or `<` in a PEP 440 range specifier as a
file-redirect operator. The command appears to run silently but produces
no output, or you see errors like:

```text
bash: main: No such file or directory
```

Or the argument is received by kanon as an empty string, causing:

```text
ERROR: list requires a catalog source.
```

### Reproducer

Run the `add` command with the spec argument unquoted, for example
`package-a@>=1.0,<2.0` without surrounding single quotes. The shell treats
`>=` as a redirect operator, creating a file named `2.0` instead of passing
the spec to kanon.

### Fix

Quote the spec argument so the shell passes it verbatim to kanon:

```bash
kanon add 'package-a@>=1.0,<2.0' --catalog-source <url>@main
```

Double-quotes also work, but single-quotes are preferred for clarity.

### See also

- [docs/list-and-add.md](list-and-add.md) -- shell-quoting examples
- [docs/configuration.md](configuration.md)

---

## 2. Missing Catalog Source

### Symptom

Any kanon command that requires a manifest repo (`kanon list`,
`kanon add`, `kanon outdated`, `kanon why`, `kanon catalog audit`)
exits non-zero with:

```text
ERROR: <command> requires a catalog source.
Provide one of:
  --catalog-source <git-url>@<ref>      # e.g. --catalog-source https://example.com/org/manifest-repo.git@main
  KANON_CATALOG_SOURCE=<git-url>@<ref>  # set as env var, then re-run

The CLI flag takes precedence when both are set.
A catalog source identifies a manifest repo (a git repository whose
repo-specs/ directory exposes installable kanon dependencies).
See docs/catalogs-explained.md for what a manifest repo is and how to find one.
See docs/configuration.md for the full configuration reference.
```

### Reproducer

```bash
# Wrong -- no catalog source provided
kanon list
```

### Fix

Pass the catalog source via the CLI flag:

```bash
kanon list \
  --catalog-source https://example.com/org/manifest-repo.git@main
```

Or export the environment variable and re-run:

```bash
export KANON_CATALOG_SOURCE=https://example.com/org/manifest-repo.git@main
kanon list
```

For `kanon install` and `kanon doctor`, a lockfile that contains
a `[catalog].source` field is used as a fallback when neither the
flag nor the env var is set.

### See also

- [docs/configuration.md](configuration.md)
- [docs/exit-codes.md](exit-codes.md)

---

## 3. Lockfile Schema Mismatch

### Symptom

`kanon install` exits non-zero with an error indicating that the
lockfile schema version does not match the running CLI:

```text
ERROR: .kanon.lock schema version mismatch.
  Lockfile schema : 1
  CLI expects     : 2
  Remediation: upgrade kanon to the version that wrote this lockfile,
  or regenerate the lockfile with 'kanon install --refresh-lock'.
```

### Reproducer

```bash
# Install with an older kanon that wrote schema version 1,
# then upgrade kanon and re-run:
kanon install
```

### Fix

Regenerate the lockfile with the currently installed CLI:

```bash
kanon install --refresh-lock \
  --catalog-source https://example.com/org/manifest-repo.git@main
```

If you need to stay on an older schema, downgrade kanon to the
version that wrote the lockfile (check the lockfile's `schema_version`
field to identify the required release).

### See also

- [docs/lockfile.md](lockfile.md)
- [docs/configuration.md](configuration.md)

---

## 4. Branch Drift

### Symptom

When a source's revision is pinned to a branch name, `kanon install`
or `kanon doctor` emits a notice (or error with `--strict-drift`):

```text
branch drift: mysource: main tip abc123 differs from locked def456;
reusing locked SHA
```

With `--strict-drift`:

```text
ERROR: Branch drift detected -- locked SHAs differ from remote tips.
  Source 'mysource': branch 'main' locked at def456, remote tip is
  abc123.
  Remediation: run 'kanon install --refresh-lock-source mysource'
  to accept the new tip.
```

### Reproducer

```bash
# Pin a source to a branch, then let the branch advance on the
# remote, then re-run install:
kanon install
```

### Fix

Accept the new branch tip by re-resolving the drifted source:

```bash
kanon install --refresh-lock-source mysource \
  --catalog-source https://example.com/org/manifest-repo.git@main
```

To turn drift into a hard CI error (recommended for reproducible
builds), pass `--strict-drift`:

```bash
kanon install --strict-drift
```

### See also

- [docs/lockfile.md](lockfile.md)
- [docs/configuration.md](configuration.md)
- [docs/exit-codes.md](exit-codes.md)

---

## 5. Completion Cache Corruption

### Symptom

Shell completions for `kanon` return no results or produce an error
after a partial cache write or a power loss mid-refresh. `kanon doctor`
may report:

```text
WARNING: completion cache is corrupt: malformed fetched_at timestamp
in cache index; run 'kanon doctor --refresh-completion-cache' to
rebuild.
```

Or the `index.txt` file is missing entirely, causing completions to
silently return nothing.

### Reproducer

```bash
# Interrupt a completion cache refresh mid-write:
kill -9 $(pgrep -f 'kanon doctor --refresh-completion-cache')
kanon list <TAB>
```

### Fix

Invalidate and rebuild the completion cache:

```bash
kanon doctor --refresh-completion-cache
```

This deletes the cached index and fetches a fresh copy from the
configured catalog source.

### See also

- [docs/shell-completion.md](shell-completion.md)
- [docs/configuration.md](configuration.md)

---

## 6. Missing `catalog-metadata` Block

### Symptom

`kanon list`, `kanon add`, or `kanon catalog audit` reports that a
`*-marketplace.xml` file is missing its `<catalog-metadata>` block:

```text
ERROR: manifest repo https://example.com/org/manifest-repo.git@main
has integrity issues (1); the catalog author must fix these via
'kanon catalog audit'. Affected entries:
  repo-specs/my-service-marketplace.xml: missing <catalog-metadata>
```

### Reproducer

```bash
kanon list \
  --catalog-source https://example.com/org/manifest-repo.git@main
```

Against a manifest repo where one XML file lacks `<catalog-metadata>`.

### Fix

This is a catalog-authoring issue. The operator cannot fix it from
the consumer side. Ask the catalog author to:

1. Add a `<catalog-metadata>` block to the affected XML file.
2. Run `kanon catalog audit .` to verify the fix.
3. Push a new tag or commit so consumers can reference the updated
   manifest repo.

### See also

- [docs/catalog-author-guide.md](catalog-author-guide.md)
- [docs/configuration.md](configuration.md)

---

## 7. Entry-Name Collision

### Symptom

Two `*-marketplace.xml` files in the same manifest repo declare the
same `<catalog-metadata><name>` value. `kanon list`, `kanon add`, or
`kanon catalog audit` reports:

```text
ERROR: manifest repo https://example.com/org/manifest-repo.git@main
has integrity issues (1); the catalog author must fix these via
'kanon catalog audit'. Affected entries:
  entry-name 'my-service' appears in 2 files:
    repo-specs/my-service-marketplace.xml
    repo-specs/legacy/my-service-marketplace.xml
```

### Reproducer

```bash
kanon list \
  --catalog-source https://example.com/org/manifest-repo.git@main
```

Against a manifest repo with a name collision.

### Fix

This is a catalog-authoring issue. Ask the catalog author to:

1. Rename one of the conflicting entries in its `<catalog-metadata>`.
2. Run `kanon catalog audit .` to confirm uniqueness.
3. Push an updated tag so consumers reference the fixed revision.

### See also

- [docs/catalog-author-guide.md](catalog-author-guide.md)
- [docs/configuration.md](configuration.md)

---

## 8. Git Auth Failure

### Symptom

`kanon install`, `kanon add`, or any command that performs a
`git ls-remote` or `git clone` exits non-zero with:

```text
ERROR: git authentication failed against
https://example.com/org/manifest-repo.git.
See docs/git-auth-setup.md.
<raw git stderr below>
fatal: Authentication failed for
'https://example.com/org/manifest-repo.git/'
```

Or for SSH:

```text
ERROR: git authentication failed against
git@example.com:org/manifest-repo.git.
See docs/git-auth-setup.md.
git@example.com: Permission denied (publickey).
```

### Reproducer

```bash
# Run against a repo you have no credentials for:
kanon list \
  --catalog-source https://private.example.com/org/repo.git@main
```

### Fix

kanon does not manage credentials. Configure git authentication for
the affected host in your local git client:

- HTTPS: configure a credential helper (OAuth, PAT, or OS keychain).
- SSH: ensure your SSH key is added to `ssh-agent` and the host
  accepts it.

After configuring git auth, re-run the kanon command. kanon does not
retry auth failures.

### See also

- [docs/git-auth-setup.md](git-auth-setup.md) -- platform-specific
  authentication guides
- [docs/configuration.md](configuration.md)

---

## 9. Partial Clone After SIGTERM

### Symptom

A `kanon install` that was interrupted (SIGTERM, SIGINT, or power
loss) leaves a partially-cloned project directory under
`.kanon-data/sources/<name>/`. Subsequent `kanon install` runs may
report:

```text
ERROR: clone directory .kanon-data/sources/my-service/.repo is
incomplete; the previous install was interrupted. Run
'kanon clean --orphans' to remove partial clones, then re-run
'kanon install'.
```

### Reproducer

```bash
# Interrupt install mid-clone:
kanon install &
kill -SIGTERM $!
# Re-run:
kanon install
```

### Fix

Remove partial project clones and re-run install:

```bash
kanon clean --orphans
kanon install
```

`kanon clean --orphans` removes per-project clone directories that
are not referenced by the current `.kanon` or `.kanon.lock`. The
lockfile itself is atomic (write-temp-then-rename), so it is either
complete or absent; only the per-project clone directories may be
partial.

### See also

- [docs/lockfile.md](lockfile.md)
- [docs/configuration.md](configuration.md)
- [docs/exit-codes.md](exit-codes.md)

---

## 10. Zero PEP 440 Tags in Manifest Repo

### Symptom

`kanon add foo` (no `@spec`) against a manifest repo entry whose
resolution target has only non-PEP-440 git tags (e.g., `v1.0.0`,
`release-2024`) exits non-zero with:

```text
ERROR: manifest repo has no PEP 440-valid tags; pin to a branch or
SHA explicitly (e.g., 'kanon add foo@main') or ask the catalog author
to publish a release tag.
Non-PEP-440 tags found under prefix '':
  v1.0.0
  release-2024
```

### Reproducer

```bash
# Against a manifest repo with only non-PEP-440 tags:
kanon add foo \
  --catalog-source https://example.com/org/manifest-repo.git@main
```

### Fix

**Option 1: Use a branch pin.**

Explicitly specify a branch or SHA instead of relying on the default
latest-PEP-440-tag resolution:

```bash
kanon add 'foo@main' \
  --catalog-source https://example.com/org/manifest-repo.git@main
```

**Option 2: Ask the catalog author to rename tags.**

Ask the catalog author to rename the non-PEP-440 tags (e.g.,
`v1.0.0` -> `1.0.0`) so they are addressable by kanon's resolver.
After the catalog author pushes PEP-440-compliant tags, re-run
`kanon add foo` without an explicit spec.

### See also

- [docs/catalog-author-guide.md](catalog-author-guide.md)
- [docs/configuration.md](configuration.md)
- [docs/exit-codes.md](exit-codes.md)

---

## 11. REPO_URL and REPO_REV Legacy Env-Var Warnings

### Symptom

`kanon install` emits a combined deprecation warning to stderr when
`REPO_URL` and/or `REPO_REV` are set. If both are set:

```text
DeprecationWarning: REPO_URL and REPO_REV environment variable(s) are
deprecated and no longer used by 'kanon install'. Use --catalog-source
to specify a remote catalog source instead.
```

If only one is set (for example, `REPO_URL` only):

```text
DeprecationWarning: REPO_URL environment variable(s) are deprecated and
no longer used by 'kanon install'. Use --catalog-source to specify a
remote catalog source instead.
```

The message is also written directly to stderr so it appears in CI logs
regardless of Python's active warning filter. The command continues to
run, but the values of `REPO_URL` and `REPO_REV` are ignored; they do
not affect resolution.

### Reproducer

```bash
REPO_URL=https://example.com/repo.git \
REPO_REV=main \
  kanon install
```

### Fix

Unset the legacy env vars from your shell and CI environment:

```bash
unset REPO_URL
unset REPO_REV
```

Then pass the catalog source explicitly via the CLI flag or env var:

```bash
kanon install \
  --catalog-source https://example.com/org/manifest-repo.git@main
```

Or export the env var:

```bash
export KANON_CATALOG_SOURCE=https://example.com/org/manifest-repo.git@main
kanon install
```

### See also

- [docs/configuration.md](configuration.md)
- [docs/exit-codes.md](exit-codes.md)

---

## See Also

The following documents provide broader context:

- [docs/configuration.md](configuration.md) -- all environment
  variables and CLI flags
- [docs/exit-codes.md](exit-codes.md) -- non-zero exit code meanings
- [docs/git-auth-setup.md](git-auth-setup.md) -- authentication
  guides for common platforms
- [docs/catalog-author-guide.md](catalog-author-guide.md) -- how to
  create and maintain a manifest repo
- [docs/lockfile.md](lockfile.md) -- lockfile schema and semantics
- [docs/shell-completion.md](shell-completion.md) -- shell completion
  setup and cache management

---

## 12. Canonical-URL Conflict

### Symptom

`kanon install` exits non-zero with:

```text
ERROR: Canonical-URL conflict -- two or more sources declare the same
repository URL with different SHAs.
  Conflict for canonical URL:
    https://gitserver/org/example-package
  source-a/manifest.xml:
    git@gitserver:org/example-package.git @ aaaa...aaaa
  source-b/manifest.xml:
    https://gitserver/org/example-package.git @ bbbb...bbbb
  both URLs canonicalize to:
    https://gitserver/org/example-package
  Remediation: Use 'kanon why https://gitserver/org/example-package'
  to investigate; resolve by removing one source or aligning REVISION
  values across sources.
```

### Reproducer

```bash
# Two sources pointing to the same repo with different SHAs:
kanon install
```

### Fix

**Option 1: Align the revision specs.**

Edit `.kanon` so that all declarations use the same `REVISION`
value (e.g., `==1.2.0`) for the conflicting repository.

**Option 2: Remove one conflicting source.**

```bash
kanon remove <source-name>
kanon install
```

**Option 3: Investigate with `kanon why`.**

```bash
kanon why https://gitserver/org/example-package
```

### See also

- [docs/configuration.md](configuration.md)
- [docs/lockfile.md](lockfile.md)
- [docs/exit-codes.md](exit-codes.md)

---

## 13. Lockfile Hash Mismatch

### Symptom

```text
ERROR: .kanon has been modified since the lockfile was written.
  Lockfile kanon_hash : sha256:aabb...
  Current  kanon_hash : sha256:ccdd...
  Remediation: run 'kanon install --refresh-lock' ...
```

### Reproducer

```bash
# Edit .kanon after the last install, then re-run:
kanon install
```

### Fix

Re-resolve from scratch:

```bash
kanon install --refresh-lock \
  --catalog-source <url>@<ref>
```

Or re-resolve just the changed source:

```bash
kanon install --refresh-lock-source <name> \
  --catalog-source <url>@<ref>
```

### See also

- [docs/lockfile.md](lockfile.md)
- [docs/configuration.md](configuration.md)

---

## 14. Lockfile SHA Unreachable

### Symptom

```text
ERROR: Lockfile SHA for source '<name>' is no longer reachable.
  Source  : <name>
  SHA     : <sha>
  Remote  : <url>
  Remediation: run 'kanon install --refresh-lock-source <name>' ...
```

### Reproducer

```bash
# After a force-push or tag removal that removes the pinned commit:
kanon install
```

### Fix

```bash
kanon install --refresh-lock-source <name> \
  --catalog-source <url>@<ref>
```

### See also

- [docs/lockfile.md](lockfile.md)
- [docs/configuration.md](configuration.md)

---

## 15. Orphaned Lock Entries

### Symptom

```text
pruned orphaned lock entry: <name>
```

Or with `--strict-lock`:

```text
ERROR: Lockfile contains orphaned sources not present in .kanon.
  Orphaned sources: '<name>'
  ...
```

### Reproducer

```bash
# Remove a source from .kanon, then re-run install with --strict-lock:
kanon remove <name>
kanon install --strict-lock
```

### Fix

Without `--strict-lock`, orphaned entries are pruned automatically.
With `--strict-lock`, re-run without the flag to accept the prune,
or restore the missing source triples to `.kanon`.

### See also

- [docs/lockfile.md](lockfile.md)
- [docs/configuration.md](configuration.md)

---

## 16. Workspace Lock Contention

### Symptom

A `kanon install`, `kanon add`, `kanon remove`, or
`kanon doctor --refresh-completion-cache` invocation hangs
indefinitely without producing output.

### Reproducer

```bash
# Run two concurrent installs:
kanon install &
kanon install
```

### Fix

Use `lsof` to find the holding process:

```bash
lsof .kanon-data/.kanon-install.lock
```

Wait for the holder to finish. If the process is stale:

```bash
kill <PID>
```

After the holder exits, the waiting kanon command proceeds
automatically.

### See also

- [docs/configuration.md](configuration.md)
- [docs/exit-codes.md](exit-codes.md)

---

## 17. Insecure Remote URL

### Symptom

```text
ERROR: Insecure <remote> URL detected in resolved manifest.
  Source  : mysource
  Remote  : mysource
  URL     : http://example.com/repo.git
  Remediation: Use an HTTPS or SSH <remote> URL, or set
  KANON_ALLOW_INSECURE_REMOTES=1 if this is intentional
  (the override disables the security check).
```

### Reproducer

```bash
# A source using an http:// URL:
kanon install
```

### Fix

**Option 1: Switch to HTTPS or SSH (recommended).**

```ini
KANON_SOURCE_mysource_URL=https://example.com/repo.git
```

**Option 2: Override the check (use with caution).**

```bash
KANON_ALLOW_INSECURE_REMOTES=1 kanon install .kanon
```

### See also

- [docs/configuration.md](configuration.md)
- [docs/exit-codes.md](exit-codes.md)
