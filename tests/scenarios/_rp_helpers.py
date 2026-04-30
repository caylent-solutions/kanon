"""Shared helpers for RP-* scenario tests.

Provides the Python equivalent of the bash `rp_ro_setup()` function defined
in §22 of `docs/integration-testing.md`, along with the fixture-builder that
creates a two-project manifest repo referencing bare `pkg-alpha` and
`pkg-bravo` content repos served over `file://` URLs.

This module is intentionally internal (prefixed `_`) so pytest does not
collect it as a test module.
"""

from __future__ import annotations

import pathlib

from tests.scenarios.conftest import make_plain_repo, run_kanon


def build_rp_ro_manifest(base: pathlib.Path) -> pathlib.Path:
    """Build the two-project manifest repo used by rp_ro_setup.

    Creates:
      <base>/content-repos/pkg-alpha.git
      <base>/content-repos/pkg-bravo.git
      <base>/manifest-repos/manifest-primary.git
        repo-specs/remote.xml   -- defines `local` remote
        repo-specs/packages.xml -- declares both projects

    Returns the bare manifest repo path.
    """
    content_repos = base / "content-repos"
    content_repos.mkdir(parents=True, exist_ok=True)
    make_plain_repo(content_repos, "pkg-alpha", {"README.md": "# pkg-alpha\n"})
    make_plain_repo(content_repos, "pkg-bravo", {"README.md": "# pkg-bravo\n"})
    content_url = content_repos.as_uri()

    remote_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{content_url}/" />\n'
        '  <default remote="local" revision="main" sync-j="2" />\n'
        "</manifest>\n"
    )
    packages_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <include name="repo-specs/remote.xml" />\n'
        '  <project name="pkg-alpha" path=".packages/pkg-alpha"'
        ' remote="local" revision="main" />\n'
        '  <project name="pkg-bravo" path=".packages/pkg-bravo"'
        ' remote="local" revision="main" />\n'
        "</manifest>\n"
    )
    manifest_repos = base / "manifest-repos"
    manifest_repos.mkdir(parents=True, exist_ok=True)
    return make_plain_repo(
        manifest_repos,
        "manifest-primary",
        {
            "repo-specs/remote.xml": remote_xml,
            "repo-specs/packages.xml": packages_xml,
        },
    )


def rp_ro_setup(work_dir: pathlib.Path, manifest_bare: pathlib.Path) -> None:
    """Initialise and sync a repo workspace.

    Mirrors the bash helper::

        rp_ro_setup() {
            mkdir -p "${KANON_TEST_ROOT}/${1}"
            cd "${KANON_TEST_ROOT}/${1}"
            kanon repo init -u "file://${MANIFEST_PRIMARY_DIR}" -b main -m repo-specs/packages.xml
            kanon repo sync
        }
    """
    work_dir.mkdir(parents=True, exist_ok=True)
    init_result = run_kanon(
        "repo",
        "init",
        "-u",
        manifest_bare.as_uri(),
        "-b",
        "main",
        "-m",
        "repo-specs/packages.xml",
        cwd=work_dir,
    )
    assert init_result.returncode == 0, f"repo init failed: stdout={init_result.stdout!r} stderr={init_result.stderr!r}"
    sync_result = run_kanon("repo", "sync", "--jobs=2", cwd=work_dir)
    assert sync_result.returncode == 0, f"repo sync failed: stdout={sync_result.stdout!r} stderr={sync_result.stderr!r}"
