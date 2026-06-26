"""Synthetic fixture helper: upgrade-versioned manifest repo.

Materialises a bare git repository whose manifest.xml declares a
<remote> element and a <default> element BEFORE any <project> element,
and whose commit graph carries multiple PEP 440-valid annotated tags
(0.1.0, 0.2.0, 1.0.0). This satisfies the repo-tool schema requirement
tested in test_synthetic_upgrade_versioned_fixture.py.

The three-tag set exercises both single-version-bump (0.1.0 -> 0.2.0)
and multi-version-bump (0.1.0 -> 1.0.0) upgrade detection in
`kanon outdated` and `kanon install --refresh-lock-source`. Each tag
is an annotated git tag so that `git ls-remote --tags` returns them
with the dereferenced `^{}` suffix expected by the kanon version
resolver.

The fake fetch URL uses the RFC 6761 `.invalid` TLD
(https://test.invalid/x), which is guaranteed non-routable per RFC 6761
section 6.4. This prevents accidental network reach during pytest runs
even when KANON_ALLOW_INSECURE_REMOTES=1 is set in the test environment.

Pattern follows _create_manifest_repo_with_tags from
tests/integration/test_add_core.py (lines 88-126).
"""

import pathlib
import subprocess


_GIT_USER_NAME = "Test User"
_GIT_USER_EMAIL = "test@example.com"

_UPGRADE_VERSIONED_MANIFEST_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="x" fetch="https://test.invalid/x"/>
  <default remote="x" revision="main"/>
  <project name="entry" path="entry" />
</manifest>
"""

_VERSIONED_TAGS = ("0.1.0", "0.2.0", "1.0.0")


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


def create_upgrade_versioned_repo_fixture(tmp_path: pathlib.Path) -> pathlib.Path:
    """Materialise a bare git repo with <remote> + <default> manifest and 3 annotated tags.

    The emitted manifest.xml has the following shape, with both <remote>
    and <default> appearing BEFORE any <project> element -- satisfying the
    repo-tool schema requirement that caused FIXTURE-DEFECT-001:

        <manifest>
          <remote name="x" fetch="https://test.invalid/x"/>
          <default remote="x" revision="main"/>
          <project name="entry" path="entry" />
        </manifest>

    The commit graph carries 3 PEP 440-valid annotated tags (0.1.0, 0.2.0,
    1.0.0). Each tag is created on a distinct commit so that the tag ordering
    in the git history is deterministic. The three-tag set exercises:
    - Single-version-bump upgrade detection: 0.1.0 -> 0.2.0
    - Multi-version-bump upgrade detection: 0.1.0 -> 1.0.0

    The fetch URL uses the RFC 6761 `.invalid` TLD so that it is
    guaranteed non-routable per RFC 6761 section 6.4; no network access
    occurs during tests.

    Args:
        tmp_path: A pytest-provided temporary directory. Sub-directories
                  are created inside it without polluting the caller's cwd.

    Returns:
        The absolute path to the bare git repository containing manifest.xml
        on the `main` branch, with annotated tags 0.1.0, 0.2.0, and 1.0.0.

    Raises:
        RuntimeError: If any underlying git command exits non-zero.
    """
    work_dir = tmp_path / "upgrade-versioned-work"
    work_dir.mkdir(parents=True, exist_ok=True)
    _init_git_work_dir(work_dir)

    manifest_path = work_dir / "manifest.xml"
    manifest_path.write_text(_UPGRADE_VERSIONED_MANIFEST_XML, encoding="utf-8")

    _git(["add", "manifest.xml"], cwd=work_dir)
    _git(["commit", "-m", "Add upgrade-versioned manifest with remote and default"], cwd=work_dir)

    first_tag, *remaining_tags = _VERSIONED_TAGS
    _git(["tag", "-a", first_tag, "-m", f"Release {first_tag}"], cwd=work_dir)

    for version in remaining_tags:
        (work_dir / "CHANGELOG.md").write_text(f"## {version}\n\nRelease {version}.\n", encoding="utf-8")
        _git(["add", "CHANGELOG.md"], cwd=work_dir)
        _git(["commit", "-m", f"Bump to {version}"], cwd=work_dir)
        _git(["tag", "-a", version, "-m", f"Release {version}"], cwd=work_dir)

    bare_dir = _clone_as_bare(work_dir, tmp_path / "upgrade-versioned-bare.git")
    return bare_dir
