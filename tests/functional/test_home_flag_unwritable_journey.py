"""Functional subprocess journey for an unwritable kanon home (item 12).

Black-box assertions against the real ``kanon`` CLI (``python -m kanon_cli``):

- An unwritable ``KANON_HOME`` makes ``kanon install`` exit non-zero with a
  message that names both the offending store path and the ``KANON_HOME`` env
  var. There is no silent relocation to the cwd.
- The same fail-fast holds when the home is supplied via the ``--home`` global
  flag pointing at an unwritable parent, with the resolved path named in the
  message (the flag is threaded into ``KANON_HOME`` so the contract is shared).

Both cases build a minimal project ``.kanon`` so install reaches the store
resolution step. The unwritable condition is created by chmod-ing a parent
directory to read+execute only (no write), so the store subdir cannot be
created. The test is skipped when running as root (root bypasses the mode bits).
"""

from __future__ import annotations

import os
import pathlib
import stat
import subprocess
import sys

import pytest


_SKIP_AS_ROOT = pytest.mark.skipif(
    os.geteuid() == 0,
    reason="root bypasses POSIX mode bits, so an unwritable directory is still writable",
)


def _write_project_kanon(directory: pathlib.Path, source_name: str = "build") -> pathlib.Path:
    """Write a minimal URL-based .kanon file into directory and return its path."""
    kanonenv = directory / ".kanon"
    kanonenv.write_text(
        f"KANON_SOURCE_{source_name}_URL=https://example.com/{source_name}.git\n"
        f"KANON_SOURCE_{source_name}_REF=main\n"
        f"KANON_SOURCE_{source_name}_PATH=meta.xml\n"
        f"KANON_SOURCE_{source_name}_NAME={source_name}\n"
        f"KANON_SOURCE_{source_name}_GITBASE=https://example.com\n",
        encoding="utf-8",
    )
    return kanonenv


def _make_unwritable_home(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a read-only parent and return a home path under it that cannot be created."""
    readonly_parent = tmp_path / "readonly_parent"
    readonly_parent.mkdir()
    readonly_parent.chmod(stat.S_IRUSR | stat.S_IXUSR)
    return readonly_parent / "kanon_home"


def _run_install(
    project: pathlib.Path, env_overrides: dict[str, str], extra_args: list[str]
) -> subprocess.CompletedProcess[str]:
    """Run ``kanon [extra_args] install <project/.kanon>`` and capture the result."""
    env = dict(os.environ)
    env["KANON_SKIP_UPDATE_CHECK"] = "1"
    env.update(env_overrides)
    kanonenv = project / ".kanon"
    return subprocess.run(
        [sys.executable, "-m", "kanon_cli", *extra_args, "install", str(kanonenv)],
        cwd=str(project),
        env=env,
        capture_output=True,
        text=True,
    )


@_SKIP_AS_ROOT
@pytest.mark.functional
def test_unwritable_kanon_home_env_fails_fast(tmp_path: pathlib.Path) -> None:
    """An unwritable KANON_HOME exits non-zero naming the path and KANON_HOME."""
    project = tmp_path / "project"
    project.mkdir()
    _write_project_kanon(project)
    unwritable_home = _make_unwritable_home(tmp_path)

    try:
        result = _run_install(project, {"KANON_HOME": str(unwritable_home)}, [])
    finally:
        unwritable_home.parent.chmod(stat.S_IRWXU)

    combined = result.stdout + result.stderr
    assert result.returncode != 0, f"install must fail on an unwritable KANON_HOME; output: {combined!r}"
    assert "KANON_HOME" in combined, f"error must name the KANON_HOME env var; got: {combined!r}"
    assert str(unwritable_home) in combined, f"error must name the offending path; got: {combined!r}"
    assert not (project / ".packages").exists(), "there must be no silent relocation to the cwd"


@_SKIP_AS_ROOT
@pytest.mark.functional
def test_unwritable_home_flag_fails_fast(tmp_path: pathlib.Path) -> None:
    """An unwritable --home path exits non-zero naming the resolved path and KANON_HOME."""
    project = tmp_path / "project"
    project.mkdir()
    _write_project_kanon(project)
    unwritable_home = _make_unwritable_home(tmp_path)

    try:
        result = _run_install(project, {}, ["--home", str(unwritable_home)])
    finally:
        unwritable_home.parent.chmod(stat.S_IRWXU)

    combined = result.stdout + result.stderr
    assert result.returncode != 0, f"install must fail on an unwritable --home; output: {combined!r}"
    assert "KANON_HOME" in combined, f"error must name the KANON_HOME contract; got: {combined!r}"
    assert str(unwritable_home) in combined, f"error must name the offending --home path; got: {combined!r}"
    assert not (project / ".packages").exists(), "there must be no silent relocation to the cwd"
