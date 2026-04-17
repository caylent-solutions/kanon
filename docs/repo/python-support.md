# Supported Python Versions

## Summary

Python 3.11 or later is required. Kanon is tested against Python 3.11, 3.12, 3.13, and 3.14.

## repo hooks

Projects that use [repo hooks] run on independent schedules.
Since it's not possible to detect what version of Python the hooks were written
or tested against, kanon always imports and execs them with the active Python
version.

If the user's Python is too new for the [repo hooks], it is up to the hooks
maintainer to update.

## Older Python Versions

Python versions below 3.11 are not supported.

[repo hooks]: ./repo-hooks.md
