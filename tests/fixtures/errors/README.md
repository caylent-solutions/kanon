# Error Fixture Files

This directory holds verbatim reference snapshots of the 8 canonical
operator-facing error messages defined by spec R128. Each fixture is the
canonical text the user sees on stderr when the corresponding error fires.

## Fixture Format

All files in this directory conform to the following invariants:

- **Encoding**: UTF-8 (no ANSI escape sequences, no terminal colour codes).
- **Line endings**: LF (`\n`) throughout.
- **Trailing newline**: exactly one trailing newline; no blank final line.
- **Content**: the full `ERROR: ...` block per the spec Section 4 header
  shape -- one summary line, optional context lines (wrapped at 80 columns),
  optional remediation line.

## Fixture Inventory

| File | Spec section | Requirement |
|------|-------------|-------------|
| `missing-catalog-source.txt` | spec Section 4 header (R124) | Canonical error when `--catalog-source` and `KANON_CATALOG_SOURCES` are both absent for a command that requires a catalog source. The `<command>` placeholder is instantiated as `list`. |
| `lockfile-hash-mismatch.txt` | lockfile state table (R128) | Error when `.kanon` has been modified since the lockfile was written (SHA-256 of the canonical key set has changed). Emitted by `kanon install --strict-lock` (the npm-ci path); plain `kanon install` reconciles the change instead of erroring. |
| `lockfile-sha-unreachable.txt` | spec Section 4.7 state table (R128) | Error when `.kanon.lock` records a resolved SHA that the remote no longer exposes. |
| `entry-not-found.txt` | spec Section 4.2 step 3 / Section 4.3 (R128) | Error when the requested catalog entry name is not found in the manifest repo. |
| `source-collision.txt` | spec Section 4.2 pre-flight (R128) | Error when `kanon add` detects that the derived source name already has a block in the destination `.kanon` file and `--force` was not supplied. |
| `conflict-detected.txt` | package destination invariant (R128) | Error when two sources resolve the same package destination path (`.packages/<name>`) to different content SHAs. The same repo at different commits for different paths is allowed; only a same-path/different-content clash is an error. |
| `missing-required-metadata-field.txt` | spec Section 3.5 soft-spot 1 (R128) | Error when a `*-marketplace.xml` is missing a required `<catalog-metadata>` field. Emitted by `kanon add` (and any command that builds the entry catalog) when the manifest repo has integrity issues. |
| `zero-pep440-tags-under-prefix.txt` | spec Section 0.4 / Section 4.2 step 4 (R190) | Error when `kanon add <name>` (no explicit `@<spec>`) finds that the manifest repo has no PEP 440-valid release tags. |

## Dynamic Values in Fixtures

Fixture files that represent errors with dynamic content (SHA hashes, file
paths, URLs, source names) use short, recognisable example values. The
snapshot test in `tests/functional/test_error_snapshots.py` uses the SAME
concrete inputs when triggering each error, so the comparison is byte-for-byte
exact.

## Drift and Remediation

If source-side error text diverges from a fixture:

1. The snapshot test in `tests/functional/test_error_snapshots.py` reports
   the mismatch.
2. The canonical authority is the spec -- NOT the source code.
3. Source-side drift must be remediated in `E15-F6-S1-T3` (cross-check and
   fix), which compares source error strings against these fixtures and
   updates the source to match.

Do NOT update a fixture to match drifted source text. Update the source to
match the fixture instead.
