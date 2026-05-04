"""Verify that built distribution archives contain no duplicate paths.

PyPI's archive-integrity policy (https://docs.pypi.org/archives/) rejects
wheels whose ZIP archive contains the same path in multiple local headers,
even when the entries are byte-identical. ``python -m build`` only emits a
non-fatal ``UserWarning: Duplicate name: ...`` and ships the wheel anyway,
so the failure surfaces only at upload time -- after the version has been
tagged. This script makes the failure deterministic at build time so it
can be wired into ``make distcheck`` and run on every PR / main / local
build.

Usage:
    python scripts/check_archive_no_duplicates.py <dist-dir>

Exits non-zero if any ``dist-dir/*.whl`` or ``dist-dir/*.tar.gz`` archive
contains duplicate paths, printing the offending paths for each archive.
Stdlib-only (zipfile + tarfile); no third-party dependency.
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import sys
import tarfile
import zipfile


def _duplicates(names: list[str]) -> list[str]:
    counts = collections.Counter(names)
    return sorted(name for name, count in counts.items() if count > 1)


def _names_in_wheel(path: pathlib.Path) -> list[str]:
    with zipfile.ZipFile(path) as zf:
        return [info.filename for info in zf.infolist()]


def _names_in_sdist(path: pathlib.Path) -> list[str]:
    with tarfile.open(path, "r:gz") as tf:
        return [member.name for member in tf.getmembers()]


def _check(path: pathlib.Path) -> tuple[int, list[str]]:
    if path.suffix == ".whl":
        names = _names_in_wheel(path)
    elif path.name.endswith(".tar.gz"):
        names = _names_in_sdist(path)
    else:
        raise ValueError(f"Unsupported archive: {path}")
    return len(names), _duplicates(names)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dist_dir", type=pathlib.Path, help="Directory containing built archives")
    args = parser.parse_args()

    archives = sorted([*args.dist_dir.glob("*.whl"), *args.dist_dir.glob("*.tar.gz")])
    if not archives:
        print(f"ERROR: no .whl or .tar.gz archives found under {args.dist_dir}", file=sys.stderr)
        return 1

    failed = False
    for archive in archives:
        total, dups = _check(archive)
        if dups:
            failed = True
            print(f"FAIL: {archive.name} -- {len(dups)} duplicated path(s) across {total} entries:", file=sys.stderr)
            for name in dups:
                print(f"  {name}", file=sys.stderr)
        else:
            print(f"OK:   {archive.name} -- {total} entries, no duplicates")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
