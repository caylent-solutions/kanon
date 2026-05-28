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
- `KANON_CATALOG_SOURCE=<git-url>@<ref>` environment variable

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
  KANON_CATALOG_SOURCE=<git-url>@<ref>
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

### Traceability

The live-resolve path was introduced as the fix for **DEFECT-008**. See
the `[Unreleased]` `### Fixed` section in [CHANGELOG.md](../CHANGELOG.md)
for the changelog entry, and
`spec/defect-resolution-and-fixture-automation-2026-06/spec.md` Section 4
E31 for the specification decision record. For the full `kanon why` flag
reference see [docs/outdated-and-why.md](outdated-and-why.md).
