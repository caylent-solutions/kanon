# Help Fixture Files

This directory contains verbatim snapshots of `kanon --help` output, used by
the parametrised snapshot harness in `tests/functional/test_help_snapshots.py`.
Each fixture is compared byte-for-byte against the live subprocess output; a
mismatch causes the test to fail with the fixture path and captured byte-count
so you can regenerate quickly.

## Naming Convention

| Pattern | Command | Notes |
|---------|---------|-------|
| `kanon-toplevel.txt` | `kanon --help` (top-level entry point) | |
| `kanon-<command>.txt` | `kanon <command> --help` | |
| `kanon-<group>-<subcommand>.txt` | `kanon <group> <subcommand> --help` | Hyphenated filename mirrors the argv path for nested subparsers (e.g. `catalog audit` -> `kanon-catalog-audit.txt`). |

Examples:

- `kanon-toplevel.txt` -- top-level `kanon --help`
- `kanon-list.txt` -- `kanon list --help`
- `kanon-catalog.txt` -- `kanon catalog --help` (subcommand-group head)
- `kanon-catalog-audit.txt` -- `kanon catalog audit --help` (nested subparser child; hyphenated filename mirrors the `catalog audit` argv path)

## Current Fixtures

| File | Command |
|------|---------|
| `kanon-toplevel.txt` | `kanon --help` |
| `kanon-list.txt` | `kanon list --help` |
| `kanon-add.txt` | `kanon add --help` |
| `kanon-remove.txt` | `kanon remove --help` |
| `kanon-outdated.txt` | `kanon outdated --help` |
| `kanon-why.txt` | `kanon why --help` |
| `kanon-install.txt` | `kanon install --help` |
| `kanon-doctor.txt` | `kanon doctor --help` |
| `kanon-catalog.txt` | `kanon catalog --help` (subcommand-group head; lists `audit` as the available catalog operation) |
| `kanon-catalog-audit.txt` | `kanon catalog audit --help` (nested subparser child; covers `--check`, `--format`, Catalog source group; hyphenated filename mirrors the `catalog audit` argv path) |

## Regeneration Procedure

If a fixture test fails because the CLI output changed intentionally (e.g., a
new subcommand was added), regenerate the fixture by running the command with
the deterministic environment variables and redirecting stdout:

```bash
NO_COLOR=1 COLUMNS=80 env -u KANON_CATALOG_SOURCE python -m kanon_cli --help > tests/fixtures/help/kanon-toplevel.txt
```

For a subcommand fixture:

```bash
NO_COLOR=1 COLUMNS=80 env -u KANON_CATALOG_SOURCE python -m kanon_cli <command> --help > tests/fixtures/help/kanon-<command>.txt
```

The three environment controls used during regeneration match exactly what
`_clean_env()` in the test harness sets:

- `NO_COLOR=1` -- disables ANSI colour codes for deterministic plain-text output.
- `COLUMNS=80` -- pins terminal width so argparse wraps at a fixed column count.
- `env -u KANON_CATALOG_SOURCE` -- unsets the variable so ambient catalog-source
  overrides do not affect the help text.

After regenerating, run the snapshot test to confirm the fixture matches:

```bash
uv run pytest tests/functional/test_help_snapshots.py -v -k kanon-toplevel
```

Review the diff in git before committing to confirm the change is intentional.
