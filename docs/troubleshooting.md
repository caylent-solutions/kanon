# Kanon Troubleshooting Guide

This guide covers common errors and how to diagnose and resolve them.

---

## Canonical-URL Conflict

### Symptom

`kanon install` exits non-zero with an error like:

```
Error: ERROR: Canonical-URL conflict -- two or more sources declare the same repository URL with different SHAs.
  Conflict for canonical URL: https://gitserver/org/example-package
  source-a/manifest.xml: git@gitserver:org/example-package.git @ aaaa...aaaa
  source-b/manifest.xml: https://gitserver/org/example-package.git @ bbbb...bbbb
  both URLs canonicalize to: https://gitserver/org/example-package
  Remediation: Use `kanon why https://gitserver/org/example-package` to investigate; resolve by removing one source or aligning REVISION values across sources.
```

### Cause

Two top-level sources in your `.kanon` file (or two `<project>` entries within
their XML manifests) point to the same git repository via different URL forms
(e.g. SSH shorthand vs HTTPS) and pin different commit SHAs.

Because `kanon install` normalizes all repository URLs to a canonical form before
comparing, URLs that differ only in scheme (`git@` vs `https://`), user-info,
trailing `.git`, or trailing `/` are treated as the same repository. When these
canonically-identical entries resolve to different SHAs, it is a hard error --
there is no way to satisfy both simultaneously.

### Diagnosis

1. Read the error message. Each line of the form:

   ```
     <source-path>: <raw-url> @ <sha>
   ```

   names the source (as `<source-name>/<manifest-path>`), the raw URL as
   declared, and the SHA it was resolved to.

2. Identify the two (or more) conflicting sources and the canonical URL that
   triggered the match.

3. Check each source's revision spec in `.kanon` to understand why they resolve
   to different SHAs.

### Resolution

**Option 1: Align the revision specs.**

Update both (or all) conflicting sources to declare the same revision for the
conflicting repository. Edit `.kanon` so that all declarations use the same
`REVISION` value (e.g. `==1.2.0`). After aligning, re-run `kanon install`.

If both sources resolve the same revision to the same commit SHA, the conflict
is resolved and install proceeds normally.

**Option 2: Remove one conflicting source.**

If one of the conflicting sources is redundant, remove it from `.kanon`:

```bash
kanon remove <source-name>
kanon install
```

After removal, the remaining source's revision is used without conflict.

**Option 3: Investigate with `kanon why`.**

Use `kanon why <canonical-url>` to see which sources declare the conflicting
repository and what revision each pins. This is especially useful when the
conflict originates from a transitive `<include>` reference:

```bash
kanon why https://gitserver/org/example-package
```

### Example: SSH vs HTTPS URL conflict

A common scenario is when one source uses an SSH URL and another uses HTTPS for
the same repository, but they pin different versions:

**.kanon:**

```ini
KANON_SOURCE_platform_URL=git@gitserver:org/example-package.git
KANON_SOURCE_platform_REVISION==1.0.0
KANON_SOURCE_platform_PATH=manifest.xml

KANON_SOURCE_sdk_URL=https://gitserver/org/example-package.git
KANON_SOURCE_sdk_REVISION==2.0.0
KANON_SOURCE_sdk_PATH=sdk-manifest.xml
```

Both `git@gitserver:org/example-package.git` and
`https://gitserver/org/example-package.git` canonicalize to
`https://gitserver/org/example-package`. The revisions `==1.0.0` and `==2.0.0`
resolve to different SHAs, producing a conflict.

**Fix: align the revision:**

```ini
KANON_SOURCE_platform_URL=git@gitserver:org/example-package.git
KANON_SOURCE_platform_REVISION==1.0.0
KANON_SOURCE_platform_PATH=manifest.xml

KANON_SOURCE_sdk_URL=https://gitserver/org/example-package.git
KANON_SOURCE_sdk_REVISION==1.0.0
KANON_SOURCE_sdk_PATH=sdk-manifest.xml
```

When both resolve `==1.0.0` to the same SHA, `kanon install` proceeds without
error (benign diamond -- same canonical URL, same SHA).

---

## Lockfile Hash Mismatch

### Symptom

```
Error: ERROR: .kanon has been modified since the lockfile was written.
  Lockfile kanon_hash : sha256:aabb...
  Current  kanon_hash : sha256:ccdd...
  Remediation: run 'kanon install --refresh-lock' ...
```

### Cause

The `.kanon` file was edited after the last `kanon install` run. The `kanon_hash`
stored in the lockfile no longer matches the freshly-computed hash of the current
`.kanon` source triples.

### Resolution

Re-resolve from scratch:

```bash
kanon install --refresh-lock --catalog-source <url>@<ref>
```

Or re-resolve just the changed source:

```bash
kanon install --refresh-lock-source <name> --catalog-source <url>@<ref>
```

---

## Lockfile SHA Unreachable

### Symptom

```
Error: ERROR: Lockfile SHA for source '<name>' is no longer reachable.
  Source  : <name>
  SHA     : <sha>
  Remote  : <url>
  Remediation: run 'kanon install --refresh-lock-source <name>' ...
```

### Cause

The commit SHA pinned in the lockfile for the named source is no longer reachable
on the remote -- typically because the branch was force-pushed or the tag was
removed.

### Resolution

```bash
kanon install --refresh-lock-source <name> --catalog-source <url>@<ref>
```

---

## Orphaned Lock Entries

### Symptom

```
pruned orphaned lock entry: <name>
```

Or with `--strict-lock`:

```
Error: ERROR: Lockfile contains orphaned sources not present in .kanon.
  Orphaned sources: '<name>'
  ...
```

### Cause

A source was removed from `.kanon` (e.g. via `kanon remove`) but the lockfile
still contains a `[[sources]]` entry for it.

### Resolution

Without `--strict-lock`, orphaned entries are pruned automatically and an info
line is emitted. The pruned lockfile is written on disk.

With `--strict-lock`, re-run without the flag to accept the prune, or restore
the missing source triples to `.kanon`.

---

## Branch Drift

### Symptom

```
branch drift: <source>: <branch> tip <new-sha> differs from locked <old-sha>; reusing locked SHA
```

Or with `--strict-drift`:

```
Error: ERROR: Branch drift detected -- locked SHAs differ from remote branch tips.
  Source '<source>': branch '<branch>' locked at <old-sha>, remote tip is <new-sha>.
  Remediation: run 'kanon install --refresh-lock-source <source>' ...
```

### Cause

A source's `revision_spec` is a branch name (e.g. `main`), and the branch's
current tip on the remote has moved since the lockfile was written.

### Resolution

Without `--strict-drift`, the locked SHA is reused (the new branch tip is
ignored). Re-run with `--refresh-lock-source <name>` to accept the new tip:

```bash
kanon install --refresh-lock-source <name> --catalog-source <url>@<ref>
```
