"""One-shot temp space and inode watchdog for the kanon test suite.

Scans the temp namespaces the test suite uses, emits one structured JSON event
to stdout (logs as an event stream), safe-sweeps stale leaked temp, and exits
non-zero when usage crosses the configured fail threshold so a caller (a 15
minute loop or a CI gate) fails fast with an actionable message.

No sleeps: the 15 minute cadence is supplied by the caller; this tool runs once
per invocation. Stdlib only. Every threshold and path is environment driven so
nothing is hard coded.

Environment:
    KANON_TEST_TMP_ROOT       managed per-run temp root parent (default <repo>/tmp).
    TMPDIR                     volume whose space and inodes are measured (default /tmp).
    KANON_TMP_SPACE_WARN_PCT   warn at or above this disk-use percent (default 80).
    KANON_TMP_INODE_WARN_PCT   warn at or above this inode-use percent (default 80).
    KANON_TMP_FAIL_PCT         exit non-zero at or above this percent (default 95).
    KANON_TMP_STALE_MAX_AGE_S  sweep aged orphaned dirs older than this many seconds (default 7200).
    KANON_TMP_SWEEP            sweep when truthy (default "1"); set "0" to report only.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
import time


def _env_int(name: str, default: int) -> int:
    """Return an integer environment value, failing fast on a malformed value."""
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        sys.stderr.write(f"ERROR: {name} must be an integer, got {raw!r}\n")
        raise SystemExit(2) from None


def _pid_alive(pid: int) -> bool:
    """Return True when a process with the given pid is still running."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _run_root_pid(name: str) -> int | None:
    """Extract the owning pid embedded in a managed run-root dir name, or None."""
    for part in name.split("-"):
        if part.isdigit():
            return int(part)
    return None


def _measure(volume: str) -> tuple[float, float, int, int]:
    """Return (space_pct, inode_pct, free_bytes, free_inodes) for a volume."""
    usage = shutil.disk_usage(volume)
    space_pct = round(usage.used / usage.total * 100, 1) if usage.total else 0.0
    stat = os.statvfs(volume)
    total_inodes = stat.f_files
    free_inodes = stat.f_favail
    inode_pct = round((total_inodes - free_inodes) / total_inodes * 100, 1) if total_inodes else 0.0
    return space_pct, inode_pct, usage.free, free_inodes


def _sweep(run_root_parent: str, tmp_dir: str, max_age_s: int, now: float) -> list[str]:
    """Remove dead-pid managed run-roots and aged orphaned pytest and kanon temp.

    Deletes only: managed run-* roots whose embedded pid is dead; and pytest-of-*
    or kanon-* dirs whose mtime is older than max_age_s. Never deletes a live-pid
    run-root or a freshly modified directory, so it is safe to run during a live
    test run.
    """
    removed: list[str] = []
    parent = pathlib.Path(run_root_parent)
    if parent.is_dir():
        for child in parent.glob("run-*"):
            pid = _run_root_pid(child.name)
            if pid is not None and not _pid_alive(pid):
                shutil.rmtree(child, ignore_errors=True)
                if not child.exists():
                    removed.append(str(child))
    tmp = pathlib.Path(tmp_dir)
    if tmp.is_dir():
        for pattern in ("pytest-of-*", "kanon-*", "kanon_*"):
            for child in tmp.glob(pattern):
                try:
                    age = now - child.stat().st_mtime
                except OSError:
                    continue
                if age > max_age_s:
                    shutil.rmtree(child, ignore_errors=True)
                    if not child.exists():
                        removed.append(str(child))
    return removed


def main() -> None:
    """Scan, log a JSON event, safe-sweep, and fail fast above the fail threshold."""
    repo_default = str(pathlib.Path(__file__).resolve().parent.parent / "tmp")
    run_root_parent = os.environ.get("KANON_TEST_TMP_ROOT", repo_default)
    tmp_dir = os.environ.get("TMPDIR", "/tmp")
    space_warn = _env_int("KANON_TMP_SPACE_WARN_PCT", 80)
    inode_warn = _env_int("KANON_TMP_INODE_WARN_PCT", 80)
    fail_pct = _env_int("KANON_TMP_FAIL_PCT", 95)
    max_age_s = _env_int("KANON_TMP_STALE_MAX_AGE_S", 7200)
    do_sweep = os.environ.get("KANON_TMP_SWEEP", "1") not in ("0", "false", "")

    now = time.time()
    removed = _sweep(run_root_parent, tmp_dir, max_age_s, now) if do_sweep else []

    space_pct, inode_pct, free_bytes, free_inodes = _measure(tmp_dir)
    parent = pathlib.Path(run_root_parent)
    tmp = pathlib.Path(tmp_dir)
    level = "ok"
    if space_pct >= space_warn or inode_pct >= inode_warn:
        level = "warn"
    if space_pct >= fail_pct or inode_pct >= fail_pct:
        level = "fail"
    event = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "tmp_dir": tmp_dir,
        "level": level,
        "space_pct": space_pct,
        "inode_pct": inode_pct,
        "free_gib": round(free_bytes / 1024**3, 2),
        "free_inodes": free_inodes,
        "run_roots": len(list(parent.glob("run-*"))) if parent.is_dir() else 0,
        "pytest_of_dirs": len(list(tmp.glob("pytest-of-*"))) if tmp.is_dir() else 0,
        "kanon_tmp_dirs": len(list(tmp.glob("kanon-*"))) if tmp.is_dir() else 0,
        "swept": len(removed),
    }
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()
    if level == "fail":
        sys.stderr.write(
            f"ERROR: temp volume {tmp_dir} at space={space_pct}% inode={inode_pct}% "
            f"(fail threshold {fail_pct}%); sweep stale roots or free the volume before running tests\n"
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
