# kanon CLI -- Output Conventions

This document describes the output conventions that apply across all kanon
commands. For the full per-command flag reference see
[docs/cli-reference.md](cli-reference.md).

## JSON output contract

Any kanon command that supports `--format json` delegates its stdout write to
the internal `_emit_json_payload` helper (defined in `src/kanon_cli/cli.py`).
The helper's documented contract is:

> JSON commands emit a single JSON document on stdout terminated by a newline;
> stderr may contain warnings; consumers should NEVER use `2>&1` when parsing
> the JSON.

### Consumer-side implications

- **stderr is never mixed into stdout.** Warnings, deprecation notices, and
  diagnostic messages from kanon always go to stderr. The stdout stream
  produced by a `--format json` command is a clean, machine-parseable JSON
  document.
- **Do NOT redirect stderr into stdout (`2>&1`).** Appending `2>&1` to a
  `kanon ... --format json` invocation is unsupported. Even if it appears to
  work in a given environment, any kanon warning or log line will corrupt the
  JSON document and break JSON parsers downstream. This restriction applies
  regardless of whether kanon is invoked directly or via `uv run --project`.
- **Safe to pipe directly into `jq`, `python -m json.tool`, etc.** Because
  stdout is clean JSON (single document, newline-terminated), downstream tools
  that read from stdin can be connected without a sentinel or header-stripping
  step.
- **Atomic write.** The serialised JSON string and the trailing newline are
  concatenated into one string before the single `sys.stdout.write` call, so
  the entire document lands in the OS pipe buffer atomically. `sys.stdout.flush()`
  is called immediately after to drain the buffer before any subsequent stderr
  write or process exit, preserving the ordering guarantee even when stdout and
  stderr share the same file descriptor.

### Code samples

**Safe invocation -- pipe directly to `jq`:**

```bash
# kanon outdated: filter sources with available upgrades
kanon outdated --format json \
  --catalog-source https://github.com/my-org/manifest-repo.git@main \
  | jq '.[] | select(.["upgrade-type"] != "none")'

# kanon why: extract chain length for a project
kanon why https://github.com/org/myproject --format json \
  | jq '.[0] | length'
```

**Unsafe invocation -- do NOT use `2>&1` with JSON commands:**

```bash
# WRONG -- stderr warnings will corrupt the JSON document
kanon outdated --format json 2>&1 | jq '.'

# WRONG -- still unsupported even under uv run
uv run --project /path/to/project kanon outdated --format json 2>&1 | jq '.'
```

If you need to capture stderr for diagnostic purposes, redirect it to a
separate file instead:

```bash
# Capture stderr separately while keeping stdout clean for the JSON parser
kanon outdated --format json \
  --catalog-source https://github.com/my-org/manifest-repo.git@main \
  2>kanon-stderr.log \
  | jq '.'
```

### Traceability

This contract was introduced as the fix for **DEFECT-002** (JSON stream
discipline). See the `[Unreleased]` `### Fixed` section in
[CHANGELOG.md](../CHANGELOG.md) for the changelog entry, and
`spec/defect-resolution-and-fixture-automation-2026-06/spec.md` Section 4 E23
and Section 13 D3 for the specification decision record.

---

## kanon why -- resolution paths

`kanon why` resolves the dependency tree via one of two paths depending
on whether a lockfile is present.

### Lockfile-present path

When `.kanon.lock` exists (default location: `<kanon-file>.lock`, or the
path specified by `--lock-file` / `KANON_LOCK_FILE`), `kanon why` reads
the resolved SHAs directly from the lockfile without making any network
calls. The `--catalog-source` flag is not required in this path.

### Live-resolve path

When no `.kanon.lock` is present but a catalog source is resolvable,
`kanon why` walks the catalog graph to resolve each source's dependency
chain. A catalog source is resolvable when any of the following is
provided:

- `--catalog-source <git-url>@<ref>` CLI flag
- `KANON_CATALOG_SOURCES=<git-url>@<ref>` environment variable

The CLI flag takes precedence when both are set.

On the live-resolve path, `kanon why` resolves each `KANON_SOURCE_*`
entry in the `.kanon` file by calling `git ls-remote` against the
declared URL and revision. If resolution fails for any source, the
command exits with a non-zero code and the following error shape:

```text
ERROR: cannot resolve '<source-name>' via catalog walk: <reason>
Remediation: Verify --catalog-source URL + revision are reachable
and the catalog manifest is well-formed.
```

### Precondition: no catalog source and no lockfile

When both conditions are true -- no `.kanon.lock` is present AND no
catalog source is configured -- `kanon why` exits immediately with:

```text
ERROR: kanon why requires a catalog source.
Provide one of:
  --catalog-source <git-url>@<ref>
  KANON_CATALOG_SOURCES=<git-url>@<ref>
```

This diagnostic is unchanged from before the live-resolve path was
implemented. The "catalog source required when lockfile is absent"
precondition is preserved.

### Identical output format across both paths

The `--format text` and `--format json` output shapes are identical
regardless of which resolution path was used. Both paths produce the
same chain structure:

```text
# text format (default)
<source-name> -> <xml-manifest-path>@<sha> -> ... -> <project-name>@<sha>

# json format (--format json)
[
  [
    {"kind": "source", "name": "<source-name>", "ref": null, "sha": "<sha>", "url": "<url>"},
    {"kind": "include", "name": "<manifest-name>", "ref": "<path-in-repo>", "sha": "<sha>", "url": null},
    {"kind": "project", "name": "<project-name>", "ref": null, "sha": "<sha>", "url": "<canonical-url>"}
  ]
]
```

The shared `_render_text` and `_emit_json_payload` functions render both
lockfile-present and live-resolve chains through the same code path,
guaranteeing format consistency.

### Argument types: `<git-url>` and `<xml-manifest-path>`

On the live-resolve path, `kanon why` accepts three distinct argument
forms. All three are evaluated before deciding; the command errors if
two or more forms match simultaneously (ambiguity).

- **Project repo URL** (`<git-url>`) -- a full Git URL such as
  `https://github.com/org/project.git` or `git@github.com:org/project`.
  The argument is canonicalized and matched against every project node's
  canonical URL in the resolved tree.

- **XML-manifest path** (`<xml-manifest-path>`) -- an exact
  `path_in_repo` string such as `repo-specs/mylib/mylib-marketplace.xml`.
  The argument is matched by string equality against every include node's
  `ref` field in the resolved tree.

- **Source name** -- the `KANON_SOURCE_<name>` key (or its
  `derive_source_name`-normalized form). Matched against the top-level
  source nodes.

On the no-lockfile live-resolve path (no `.kanon.lock` present), the
tree is built by cloning the catalog source and walking each manifest
XML, populating the full project + include chain. URL and XML-path
lookups therefore find the same nodes as the lockfile-present path,
producing identical chain output for both forms.

### Traceability

The live-resolve path was introduced as the fix for **DEFECT-008**. See
the `[Unreleased]` `### Fixed` section in [CHANGELOG.md](../CHANGELOG.md)
for the changelog entry, and
`spec/defect-resolution-and-fixture-automation-2026-06/spec.md` Section 4
E31 for the specification decision record. URL and XML-path argument
support on the live-resolve path was confirmed and test-locked as part of
the E49 gap-closure (gap 1). The E51-F2-S1-T1 fix (BUG-2) corrected a
regression where `<git-url>` and `<xml-manifest-path>` arguments were not
matched on the live-resolve path because project and include children were
omitted from the resolved tree; the live tree is now built with the full
project + include chain. For the full `kanon why` flag reference see
[docs/outdated-and-why.md](outdated-and-why.md).

---

## kanon doctor -- per-subcheck output format

`kanon doctor` performs a series of consistency subchecks against the
`.kanon` file, `.kanon.lock` lockfile, install workspace, and completion
cache. Each subcheck produces exactly one output line on stdout.

### Output format

Each line follows one of three shapes depending on the outcome of the
subcheck:

- `[ok] <name>` -- the subcheck passed; no issues found.
- `[fail] <name>: <reason>` -- the subcheck detected a problem; `<reason>`
  describes what was found and what to do about it.
- `[info] <name>` -- the subcheck produced an informational notice;
  no action is required.

The three prefix tokens (`[ok]`, `[fail]`, `[info]`) are fixed strings
defined in `kanon_cli.constants` as `FINDING_PREFIX_OK`, `FINDING_PREFIX_FAIL`,
and `FINDING_PREFIX_INFO` respectively. They do not vary between invocation
modes.

### Subcheck names

The default `kanon doctor` run executes three subchecks whose names appear
verbatim in the output:

- `kanon_hash consistency` -- verifies the `.kanon` file hash recorded in
  the lockfile matches the current file on disk.
- `no orphaned lock entries` -- verifies every entry in `.kanon.lock` still
  has a corresponding source declared in `.kanon`.
- `no branch drift` -- verifies none of the locked sources has drifted from
  the branch tip declared in the catalog.

A sample successful default run looks like:

```text
[ok] kanon_hash consistency
[ok] no orphaned lock entries
[ok] no branch drift
```

A run that finds an orphan and a drift issue looks like:

```text
[ok] kanon_hash consistency
[fail] no orphaned lock entries: orphan lock entry: source 'oldlib' is in .kanon.lock but absent from .kanon
[fail] no branch drift: source 'mylib' has drifted from its branch tip
```

The orphaned-lock-entry remediation is to run `kanon install` (prunes the
orphan) or `kanon install --strict-lock` (keeps the lockfile authoritative
and fails on the orphan instead).

### Verbosity flag interaction

The global `--quiet` flag suppresses INFO-level lines. When `--quiet` is
set, any `[info] <name>` lines are omitted from stdout; `[ok]` and `[fail]`
lines are always emitted regardless of verbosity.

The default verbosity (no `--quiet` flag) emits all three severities.

### Exit-code contract

`kanon doctor` exits with code `0` when no `[fail]` line appears in the
output -- that is, when all subchecks produce `[ok]` or `[info]` results.

`kanon doctor` exits with a non-zero code when one or more `[fail]` lines
are present. This preserves the pre-DEFECT-012 failure-path semantics: a
non-zero exit is the authoritative signal for CI gates and scripted
consumers.

### Cache-flag workspace independence

The `--refresh-completion-cache` and `--prune-cache` flags operate on
the cache under `${KANON_HOME}/cache` and do NOT require a `.kanon` workspace to
be present in the current directory. When either flag is the only active
flag, `kanon doctor` completes the cache operation and exits without
running workspace-dependent subchecks (hash consistency, orphan
detection, branch drift).

This means the following invocations work from any directory, including
directories that contain no `.kanon` file:

```bash
# Invalidate the completion cache globally
kanon doctor --refresh-completion-cache

# Prune stale cache files by last-access time
kanon doctor --prune-cache
```

If additional workspace-dependent flags (e.g. a subcheck flag) are
supplied alongside a cache flag, workspace discovery is NOT bypassed --
all requested subchecks run as normal.

### Traceability

The per-subcheck output format was introduced as the fix for **DEFECT-012**.
Cache-flag workspace independence was introduced as the fix for
**DEFECT-013** and confirmed for the E49 gap-closure (gap 2). See the
`[Unreleased]` `### Fixed` section in [CHANGELOG.md](../CHANGELOG.md)
for the changelog entry, and
`spec/defect-resolution-and-fixture-automation-2026-06/spec.md` Section 4
E33 for the specification decision record.

---

## kanon add -- marketplace-install flags

`kanon add` accepts `--marketplace-install` and `--no-marketplace-install`
flags that override the per-dependency marketplace setting written to the
added source block. In kanon 3.0.0 the marketplace setting is **per
dependency** -- the flag controls whether a
`KANON_SOURCE_<alias>_MARKETPLACE=true` line is written into that
dependency's block. There is no global `KANON_MARKETPLACE_INSTALL` header
(it was removed in 3.0.0); see
[docs/claude-marketplaces-guide.md](claude-marketplaces-guide.md).

### Resolution

The value written for the added dependency is resolved as follows:

1. **`--marketplace-install`** -- forces the dependency to register as a
   marketplace: writes `KANON_SOURCE_<alias>_MARKETPLACE=true`. It is an
   error when the entry's `<catalog-metadata><type>` is not
   `claude-marketplace`.
2. **`--no-marketplace-install`** -- forces the dependency to NOT register
   as a marketplace: the `KANON_SOURCE_<alias>_MARKETPLACE` line is omitted
   (absence is the canonical "disabled"; kanon never writes `=false`).
3. **Neither flag** -- the setting is auto-detected from the entry's
   `<catalog-metadata><type>`: `claude-marketplace` entries get
   `_MARKETPLACE=true`, all others omit the line.

The two flags are mutually exclusive (passing both is a usage error).

### Usage examples

```bash
# Force marketplace registration -- writes KANON_SOURCE_<alias>_MARKETPLACE=true
kanon add myentry@1.0.0 --marketplace-install \
  --catalog-source https://example.com/org/manifest-repo.git@main

# Force no marketplace registration -- omits the _MARKETPLACE line
kanon add myentry@1.0.0 --no-marketplace-install \
  --catalog-source https://example.com/org/manifest-repo.git@main

# Default: setting is auto-detected from the entry's catalog <type>
kanon add myentry@1.0.0 \
  --catalog-source https://example.com/org/manifest-repo.git@main
```

To toggle the per-dependency marketplace setting after the entry is added,
use `kanon marketplace enable <alias>` / `kanon marketplace disable <alias>`
(see [docs/claude-marketplaces-guide.md](claude-marketplaces-guide.md)).

### Traceability

The per-dependency `--marketplace-install` / `--no-marketplace-install` flag
pair, the per-dependency `KANON_SOURCE_<alias>_MARKETPLACE` key, and the
`kanon marketplace` subcommands replace the removed global
`KANON_MARKETPLACE_INSTALL` header in kanon 3.0.0. For the full `kanon add`
flag reference see [docs/list-and-add.md](list-and-add.md).

---

## kanon install -- refresh-lock-source exact-pin contract

`kanon install --refresh-lock-source <name>` re-resolves exactly one
named source's full dependency chain while preserving all other
sources' lockfile entries verbatim.

### Exact-pin vs range-spec semantics

The resolved SHA after `--refresh-lock-source` depends on the source's
revision specifier in `.kanon`:

- **Exact pin** -- a `.kanon` revision that is an exact PEP 440 version
  (e.g. `==1.2.3`, or a bare tag such as `1.2.3`) always resolves to
  the same SHA. The locked SHA is unchanged after `--refresh-lock-source`
  because the exact pin constrains resolution to a single tag. This is
  correct dependency-manager semantics: an exact pin is a pin.

- **Range specifier** -- a `.kanon` revision that is a PEP 440 range or
  compatible-release specifier (e.g. `>=1.0.0,<2.0.0`, `~=1.2`) resolves
  to the highest tag in the repo that satisfies the constraint at the time
  of the refresh. The locked SHA advances when a newer satisfying tag
  exists.

- **Floating branch ref** -- a `.kanon` revision that names a branch
  (e.g. `main`) resolves to the current branch tip. The locked SHA
  advances when the branch has moved since the last install.

This behavior is test-locked. There is no mechanism to "force" an
exact pin to advance -- use a range specifier or a branch ref if the
source needs to follow new releases automatically.

### Traceability

The exact-pin vs range-spec contract was clarified and test-locked as
part of the E49 gap-closure (gap 5; operator decision recorded in the
spec Section 13 D3). See the `[Unreleased]` `### Fixed` section in
[CHANGELOG.md](../CHANGELOG.md) for the gap-5 contract note. For the
full `kanon install` flag reference see [docs/lockfile.md](lockfile.md).

---

## kanon install -- refresh-lock on an existing checkout (BUG-1)

`kanon install --refresh-lock` and `kanon install --refresh-lock-source <name>`
now succeed when the workspace is already installed (all sources already
cloned). Prior to the E51-F1-S1-T1 fix, the `repo envsubst` step left the
`.repo/manifests` working tree dirty (modified XML files and `.bak` sibling
files created by envsubst). When `repo init` was re-run with the new revision,
git refused to check out the updated manifest commit over the modified working
tree, leaving HEAD pointing to a deleted branch ref and raising an unhandled
`GitCommandError` instead of completing the refresh.

### Behaviour after fix

- Before re-running `repo init`, the `.repo/manifests` working tree is reset
  to a clean HEAD state: tracked files are restored via `git checkout -- .`
  and untracked `.bak` files are removed.
- `repo init` is then re-run with the new revision; if it fails, the error is
  caught and re-raised as a structured `RefreshRepoInitError` that names the
  offending source and provides a remediation hint, rather than a raw traceback.
- Both `--refresh-lock` (full re-resolve) and `--refresh-lock-source <name>`
  (single-source re-resolve) apply this reset-and-reinit logic identically.

### Usage examples

`kanon install` is hermetic: it re-resolves from the committed `.kanon`
source declarations and does not accept `--catalog-source`.

```bash
# Re-resolve all lock entries on an already-installed workspace -- no error
kanon install --refresh-lock

# Re-resolve one source on an already-installed workspace -- no error
kanon install --refresh-lock-source mylib
```

### Traceability

This fix was introduced in E51-F1-S1-T1 (BUG-1). For the full
`--refresh-lock` / `--refresh-lock-source` flag reference see
[docs/lockfile.md](lockfile.md).

---

## kanon install -- direct-checkout marketplace registration (BUG-3)

For source entries declared with `KANON_SOURCE_<alias>_MARKETPLACE=true`,
`kanon install` registers the Claude marketplace even for direct-checkout
entries that carry a `.claude-plugin/marketplace.json` file but no
`<linkfile>` element in the source manifest XML.

> **Note:** `kanon install` is hermetic. It does not accept `--catalog-source`
> and ignores any catalog env var; it resolves entirely from `.kanon` and
> `.kanon.lock`. Marketplace registration is driven by the per-dependency
> `KANON_SOURCE_<alias>_MARKETPLACE=true` key, not by the removed global
> `KANON_MARKETPLACE_INSTALL` env var.

### Behaviour before the fix

Before E51-F3-S1-T1, the marketplace registration loop only discovered
marketplace roots via the linkfile path: it scanned each source's manifest
XML for `<linkfile>` elements pointing at marketplace directories under
`CLAUDE_MARKETPLACES_DIR`. Sources that were cloned directly (no linkfile
in their manifest, or no manifest at all) were not inspected for
`.claude-plugin/marketplace.json`, so their marketplace was silently
skipped.

### Behaviour after fix

After the fix, the registration loop checks each cloned source directory
for `.claude-plugin/marketplace.json` regardless of whether a linkfile is
present. When the file is found, the source's root directory is passed to
`claude plugin marketplace add` exactly as it would be for a manifest-
driven entry.

The visible effect: `claude plugin marketplace list` now shows one
registered entry for every cloned source that ships `.claude-plugin/marketplace.json`,
including sources installed via direct checkout.

### Preconditions

- The source is declared with `KANON_SOURCE_<alias>_MARKETPLACE=true` in
  `.kanon` (set by `kanon add --marketplace-install` or
  `kanon marketplace enable <alias>`).
- `CLAUDE_MARKETPLACES_DIR` is present in `.kanon`. It is auto-added by
  `kanon add` of a `claude-marketplace` entry and by `kanon marketplace enable`
  (and pruned by `kanon remove` / `kanon marketplace disable` on the last
  marketplace dependency); hand-set it only to override the directory. As a
  defense-in-depth check, when a marketplace-enabled dependency is declared
  without it (e.g. a hand-edited `.kanon`), `kanon install` fails fast with an
  actionable error.
- The `claude` binary is available on `$PATH`; if absent, `kanon install`
  fails fast with a non-zero exit and an actionable error.

### Usage example

```bash
# Direct-checkout source declared with KANON_SOURCE_<alias>_MARKETPLACE=true
# is registered automatically -- install is hermetic (no --catalog-source)
kanon install
```

### Traceability

This fix was introduced in E51-F3-S1-T1 (BUG-3). For the full marketplace
configuration reference see
[docs/claude-marketplaces-guide.md](claude-marketplaces-guide.md).
