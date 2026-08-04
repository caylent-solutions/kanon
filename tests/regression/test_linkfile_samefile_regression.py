"""Regression guard: a file-level ``<linkfile>`` in a marketplace source installs.

Issue 93: ``kanon install`` exited 1 with ``shutil.SameFileError`` whenever a
source flagged ``KANON_SOURCE_<alias>_MARKETPLACE=true`` declared a
``<linkfile>`` whose ``src`` is a regular file.

``repo sync`` materializes every ``<linkfile>`` as a symlink at ``dest``
targeting ``src`` (``kanon_cli.repo.project._LinkFile._Link``).  ``install()``
then ran a second, duplicate linkfile pass that called
``shutil.copy2(src, dest)`` on that same pair, and ``shutil.copyfile`` raises
``SameFileError`` when ``src`` and ``dest`` stat to the same inode.
Directory-level linkfiles escaped because that pass skipped any ``src`` that
was not a regular file.

The duplicate pass is gone; ``repo sync`` is the single owner of ``<linkfile>``
materialization.  This module drives a real ``repo init`` + ``repo sync``
against local ``file://`` fixture repos -- no mocked sync -- so it exercises
the exact combination that crashed and fails if the duplicate pass is ever
reintroduced.

``tests/scenarios/test_lf.py`` covers file-level linkfiles on an unflagged
source.  The marketplace flag is what made this combination fail, so it is what
this module holds.
"""

from __future__ import annotations

import pathlib
import subprocess
from unittest.mock import patch

import pytest

from kanon_cli.core.install import install


_MANIFEST_XML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="local" fetch="{fetch_url}" />
  <default remote="local" revision="main" sync-j="1" />
  <project name="pkg" path=".packages/pkg">
    <linkfile src="{src}" dest="{dest}" />
  </project>
</manifest>
"""

_KANONENV_TEMPLATE = """CLAUDE_MARKETPLACES_DIR={marketplaces_dir}

KANON_SOURCE_v_NAME=filecase
KANON_SOURCE_v_URL={catalog_url}
KANON_SOURCE_v_REF=main
KANON_SOURCE_v_PATH=repo-specs/entry.xml
KANON_SOURCE_v_MARKETPLACE={marketplace_flag}
"""

_FILE_PAYLOAD = 'title = "spike"\n'
_DIR_PAYLOAD = "# rule\n"


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in ``cwd``, raising on failure.

    Args:
        args: Arguments following the ``git`` executable.
        cwd: Working directory for the command.

    Raises:
        RuntimeError: If git exits non-zero.
    """
    result = subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args} failed in {cwd}: {result.stderr}")


def _seed_repo(work: pathlib.Path, files: dict[str, str]) -> pathlib.Path:
    """Create a git repository containing ``files`` and return its path.

    Args:
        work: Directory to initialize as a git work tree.
        files: Mapping of repo-relative path to file content.

    Returns:
        The initialized repository path.
    """
    work.mkdir(parents=True)
    for rel, content in files.items():
        target = work / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    _git(["init", "-q", "-b", "main"], work)
    _git(["add", "-A"], work)
    _git(["commit", "-qm", "seed"], work)
    return work


def _build_workspace(
    tmp_path: pathlib.Path,
    *,
    linkfile_src: str,
    marketplace_flag: str,
) -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    """Build package and catalog repos plus a consumer workspace.

    Args:
        tmp_path: Test-scoped temporary directory.
        linkfile_src: The ``src`` value for the manifest ``<linkfile>``.
        marketplace_flag: Value for ``KANON_SOURCE_v_MARKETPLACE``.

    Returns:
        A tuple of the consumer workspace, its ``.kanon`` path, and the
        absolute ``dest`` the manifest links to.
    """
    origins = tmp_path / "origins"
    _seed_repo(
        origins / "pkg",
        {
            "gitleaks.toml": _FILE_PAYLOAD,
            "rules/testing.md": _DIR_PAYLOAD,
        },
    )

    consumer = tmp_path / "consumer"
    consumer.mkdir(parents=True)
    dest = consumer / ".gitleaks.toml"

    _seed_repo(
        origins / "catalog",
        {
            "repo-specs/entry.xml": _MANIFEST_XML_TEMPLATE.format(
                fetch_url=origins.as_uri(),
                src=linkfile_src,
                dest=str(dest),
            ),
        },
    )

    kanonenv = consumer / ".kanon"
    kanonenv.write_text(
        _KANONENV_TEMPLATE.format(
            marketplaces_dir=tmp_path / "marketplaces",
            catalog_url=(origins / "catalog").as_uri(),
            marketplace_flag=marketplace_flag,
        )
    )
    return consumer, kanonenv, dest


def _install_with_stubbed_claude(kanonenv: pathlib.Path, lock_file_path: pathlib.Path) -> None:
    """Run ``install()`` with the claude CLI interaction stubbed at its boundary.

    ``install_marketplace_plugins`` shells out to ``claude`` at the end of any
    run carrying a marketplace-flagged source, and that binary is absent in CI.
    It is replaced as a whole rather than by patching ``subprocess.run``:
    ``kanon_cli.core.marketplace`` imports the ``subprocess`` module itself, so
    patching ``marketplace.subprocess.run`` would replace ``subprocess.run`` for
    every caller in the process, including the real ``git`` invocations this
    module exists to exercise.

    Everything from ``repo init`` through ``repo sync`` and its ``<linkfile>``
    step runs for real.

    Args:
        kanonenv: Path to the ``.kanon`` file to install from.
        lock_file_path: Path the lockfile is written to.
    """
    with patch("kanon_cli.core.install.install_marketplace_plugins"):
        install(kanonenv, lock_file_path=lock_file_path)


@pytest.mark.integration
class TestFileLinkfileInMarketplaceSource:
    """A file ``src`` must survive the real ``repo sync`` that precedes install()."""

    @pytest.mark.parametrize("marketplace_flag", ["true", "false"], ids=["flagged", "unflagged"])
    def test_file_linkfile_installs_and_leaves_a_symlink(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        marketplace_flag: str,
    ) -> None:
        """Given: a manifest whose ``<linkfile>`` src is a regular file.

        When: ``install()`` runs a real ``repo init`` and ``repo sync``.
        Then: it completes and ``dest`` is the symlink ``repo sync`` created.

        Parameterized over the marketplace flag because the flag was the
        trigger: the duplicate linkfile pass ran only for flagged sources, so
        the unflagged case is the control that always worked.
        """
        monkeypatch.setenv("KANON_HOME", str(tmp_path / "kanon-home"))
        monkeypatch.setenv("KANON_ALLOW_INSECURE_REMOTES", "1")
        consumer, kanonenv, dest = _build_workspace(
            tmp_path,
            linkfile_src="gitleaks.toml",
            marketplace_flag=marketplace_flag,
        )

        _install_with_stubbed_claude(kanonenv, consumer / ".kanon.lock")

        assert dest.is_symlink(), f"expected the repo-managed symlink at {dest}"
        assert dest.read_text() == _FILE_PAYLOAD

    def test_directory_linkfile_installs_and_leaves_a_symlink(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Given: a manifest whose ``<linkfile>`` src is a directory.

        When: ``install()`` runs a real ``repo init`` and ``repo sync``.
        Then: it completes and ``dest`` is a symlink to that directory.

        The directory case never crashed, so this pins that removing the
        duplicate pass left it unchanged.
        """
        monkeypatch.setenv("KANON_HOME", str(tmp_path / "kanon-home"))
        monkeypatch.setenv("KANON_ALLOW_INSECURE_REMOTES", "1")
        consumer, kanonenv, dest = _build_workspace(
            tmp_path,
            linkfile_src="rules",
            marketplace_flag="true",
        )

        _install_with_stubbed_claude(kanonenv, consumer / ".kanon.lock")

        assert dest.is_symlink(), f"expected the repo-managed symlink at {dest}"
        assert (dest / "testing.md").read_text() == _DIR_PAYLOAD
