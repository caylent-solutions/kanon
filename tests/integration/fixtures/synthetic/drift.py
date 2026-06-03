"""Synthetic fixture helper: drift manifest repo.

Materialises a bare git repository whose manifest.xml declares a
<remote> element and a <default> element BEFORE any <project> element,
satisfying the repo-tool schema requirement tested in
test_synthetic_drift_fixture.py.

The fake fetch URL uses the RFC 6761 `.invalid` TLD
(https://test.invalid/x), which is guaranteed non-routable per RFC 6761
§6.4. This prevents accidental network reach during pytest runs even
when KANON_ALLOW_INSECURE_REMOTES=1 is set in the test environment.

Pattern follows _create_manifest_repo_with_tags from
tests/integration/test_add_core.py (lines 88-126).
"""

import pathlib
import subprocess


_GIT_USER_NAME = "Test User"
_GIT_USER_EMAIL = "test@example.com"

_DRIFT_MANIFEST_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="x" fetch="https://test.invalid/x"/>
  <default remote="x" revision="main"/>
  <project name="entry" path="entry" />
</manifest>
"""


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd, raising RuntimeError on non-zero exit."""
    result = subprocess.run(
        ["git"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}:\n  stdout: {result.stdout!r}\n  stderr: {result.stderr!r}")


def _init_git_work_dir(work_dir: pathlib.Path) -> None:
    """Initialise a git working directory with deterministic test user config."""
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)


def _clone_as_bare(work_dir: pathlib.Path, bare_dir: pathlib.Path) -> pathlib.Path:
    """Clone work_dir into a bare repository and return the resolved bare path."""
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=work_dir.parent)
    return bare_dir.resolve()


def create_drift_fixture(tmp_path: pathlib.Path) -> pathlib.Path:
    """Materialise a bare git repo whose manifest.xml declares <remote> + <default>.

    The emitted manifest.xml has the following shape, with both <remote>
    and <default> appearing BEFORE any <project> element -- satisfying the
    repo-tool schema requirement that caused FIXTURE-DEFECT-001:

        <manifest>
          <remote name="x" fetch="https://test.invalid/x"/>
          <default remote="x" revision="main"/>
          <project name="entry" path="entry" />
        </manifest>

    The fetch URL uses the RFC 6761 `.invalid` TLD so that it is
    guaranteed non-routable; no network access occurs during tests.

    Args:
        tmp_path: A pytest-provided temporary directory. Sub-directories
                  are created inside it without polluting the caller's cwd.

    Returns:
        The absolute path to the bare git repository containing manifest.xml
        on the `main` branch.

    Raises:
        RuntimeError: If any underlying git command exits non-zero.
    """
    work_dir = tmp_path / "drift-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(work_dir)

    manifest_path = work_dir / "manifest.xml"
    manifest_path.write_text(_DRIFT_MANIFEST_XML, encoding="utf-8")

    _git(["add", "manifest.xml"], cwd=work_dir)
    _git(["commit", "-m", "Add drift manifest with remote and default"], cwd=work_dir)

    bare_dir = _clone_as_bare(work_dir, tmp_path / "drift-bare.git")
    return bare_dir
