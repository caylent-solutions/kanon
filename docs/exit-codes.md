# kanon Exit Codes

This document lists all exit codes produced by the `kanon` CLI and their meanings.

| Code | Name | Meaning | Source |
|------|------|---------|--------|
| 0 | success | The command completed successfully. | All commands |
| 1 | runtime / usage error | An application-level error occurred: filesystem error, network error, validation failure, or a malformed input that the application detected. | All commands |
| 2 | argparse usage error | The command-line arguments were invalid. argparse emits this when a required positional is missing, an unknown flag is supplied, or a flag value fails type conversion. | `cli.py` (argparse) |
| 3 | deprecated invocation | The command was invoked via a deprecated interface. No work was performed. Follow the WARN message printed to stderr for the recommended replacement. | `kanon bootstrap` (any non-`--help` invocation) |

## Notes

- Exit code 3 was introduced alongside the deprecation of `kanon bootstrap` in favour of `kanon add` and `kanon list`.
  See `docs/migration-bootstrap-to-add.md` for the full migration guide.
- Exit codes 1 and 2 follow POSIX convention: 1 for application errors, 2 for argument-parsing errors.
- Exit code 0 is reserved exclusively for successful completion; partial success is not represented separately.
