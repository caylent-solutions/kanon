"""Integration tests: per-alias KANON_SOURCE_<alias>_GITBASE drives envsubst.

``kanon add`` records the org base for ``${GITBASE}`` resolution per dependency
in ``KANON_SOURCE_<alias>_GITBASE`` and never writes a global ``GITBASE=``
header line (spec Section 5.1 / FR-5, FR-6; commands/add.py module docstring).
The repo-tool ``envsubst`` resolves ``${GITBASE}`` from the process environment,
so ``install`` must promote each source's per-alias gitbase into ``GITBASE`` for
that source's substitution. Before the promotion was wired up, a plain
``add`` -> ``install`` on a catalog whose ``remote.xml`` uses ``${GITBASE}``
failed with ``Unresolved environment variables: GITBASE`` and left
``${GITBASE}`` unsubstituted in the manifest.

These tests exercise the real ``install()`` API against real bare git manifest
repositories with a real ``repo init`` and a real ``repo envsubst`` (only
``repo sync`` is stubbed, so the network fetch is skipped while the full
substitution path is exercised). They assert the substituted manifest contains
the per-alias org base and no longer contains the ``${GITBASE}`` placeholder,
without any global ``GITBASE=`` line in the ``.kanon`` file.
"""

import os
import pathlib
import subprocess

import pytest

from kanon_cli.constants import KANON_ALLOW_INSECURE_REMOTES
from kanon_cli.core.install import build_source_envsubst_vars, install


_GIT_USER_NAME = "Per Alias Gitbase Test"
_GIT_USER_EMAIL = "per-alias-gitbase@example.com"
_MANIFEST_NAME = "remote.xml"

_MANIFEST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${GITBASE}/repos" />
  <default revision="main" remote="origin" />
  <project name="pkg" path="pkg" />
</manifest>
"""


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd, raising RuntimeError on non-zero exit."""
    result = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}: stdout={result.stdout!r} stderr={result.stderr!r}")


def _make_manifest_bare_repo(base: pathlib.Path, slug: str) -> pathlib.Path:
    """Create a bare git repo containing a remote.xml that uses ${GITBASE}.

    Returns the path to the bare repository so the caller can build a
    ``file://`` URL for it.
    """
    work_dir = base / f"{slug}-work"
    work_dir.mkdir(parents=True)
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)
    (work_dir / _MANIFEST_NAME).write_text(_MANIFEST_TEMPLATE, encoding="utf-8")
    _git(["add", _MANIFEST_NAME], cwd=work_dir)
    _git(["commit", "-m", "manifest"], cwd=work_dir)

    bare_dir = base / f"{slug}-bare"
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=base)
    return bare_dir


def _substituted_manifest_path(alias: str) -> pathlib.Path:
    """Return the post-envsubst manifest path under the isolated KANON_HOME store.

    The ``_isolate_kanon_home`` autouse fixture points KANON_HOME at a fresh
    per-test temp dir; ``install()`` writes source artifacts under
    ``<KANON_HOME>/store/.kanon-data/sources/<alias>/``.
    """
    store_base = pathlib.Path(os.environ["KANON_HOME"]) / "store"
    return store_base / ".kanon-data" / "sources" / alias / ".repo" / "manifests" / _MANIFEST_NAME


@pytest.fixture
def _no_network_sync(monkeypatch: pytest.MonkeyPatch):
    """Stub repo sync so only repo init + repo envsubst run (no network fetch)."""
    monkeypatch.setattr("kanon_cli.repo.repo_sync", lambda *args, **kwargs: None)


@pytest.mark.integration
class TestPerAliasGitbaseDrivesEnvsubst:
    """A per-alias ``_GITBASE`` (with NO global GITBASE) must drive envsubst."""

    def test_single_source_per_alias_gitbase_substituted(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        _no_network_sync,
    ) -> None:
        """A .kanon with only KANON_SOURCE_<alias>_GITBASE (no global GITBASE)
        substitutes the per-alias org base into the manifest's ${GITBASE}.

        Falsifiability: before install promotes the per-alias gitbase into
        ``GITBASE``, envsubst sees no ``GITBASE`` in the environment, leaving
        ``${GITBASE}`` unsubstituted, so both assertions below fail.
        """
        monkeypatch.delenv("GITBASE", raising=False)
        monkeypatch.setenv(KANON_ALLOW_INSECURE_REMOTES, "1")

        repos_base = tmp_path / "repos"
        repos_base.mkdir()
        bare = _make_manifest_bare_repo(repos_base, "cpk")

        org_base = "https://github.com/caylent-per-alias"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanonenv = workspace / ".kanon"
        kanonenv.write_text(
            f"KANON_SOURCE_cpk_URL=file://{bare}\n"
            f"KANON_SOURCE_cpk_REF=main\n"
            f"KANON_SOURCE_cpk_PATH={_MANIFEST_NAME}\n"
            f"KANON_SOURCE_cpk_NAME=cpk\n"
            f"KANON_SOURCE_cpk_GITBASE={org_base}\n"
        )

        kanon_lines = kanonenv.read_text().splitlines()
        assert not any(line.startswith("GITBASE=") for line in kanon_lines), (
            "test fixture must not contain a global GITBASE line"
        )

        install(kanonenv.resolve(), lock_file_path=workspace / ".kanon.lock")

        manifest_text = _substituted_manifest_path("cpk").read_text(encoding="utf-8")
        assert "${GITBASE}" not in manifest_text, (
            f"${{GITBASE}} must be substituted using the per-alias gitbase; manifest was: {manifest_text!r}"
        )
        assert f'fetch="{org_base}/repos"' in manifest_text, (
            f"manifest must contain the per-alias org base {org_base!r}; manifest was: {manifest_text!r}"
        )

    def test_multi_source_each_uses_its_own_per_alias_gitbase(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        _no_network_sync,
    ) -> None:
        """Two sources with distinct per-alias gitbases each substitute their own.

        Falsifiability: a single shared env_vars dict (the pre-fix behaviour)
        cannot supply two different ``GITBASE`` values, so at least one source's
        manifest would carry the wrong org base or an unsubstituted placeholder.
        """
        monkeypatch.delenv("GITBASE", raising=False)
        monkeypatch.setenv(KANON_ALLOW_INSECURE_REMOTES, "1")

        repos_base = tmp_path / "repos"
        repos_base.mkdir()
        bare_alpha = _make_manifest_bare_repo(repos_base, "alpha")
        bare_beta = _make_manifest_bare_repo(repos_base, "beta")

        org_alpha = "https://github.com/org-alpha"
        org_beta = "https://github.com/org-beta"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanonenv = workspace / ".kanon"
        kanonenv.write_text(
            f"KANON_SOURCE_alpha_URL=file://{bare_alpha}\n"
            f"KANON_SOURCE_alpha_REF=main\n"
            f"KANON_SOURCE_alpha_PATH={_MANIFEST_NAME}\n"
            f"KANON_SOURCE_alpha_NAME=alpha\n"
            f"KANON_SOURCE_alpha_GITBASE={org_alpha}\n"
            f"KANON_SOURCE_beta_URL=file://{bare_beta}\n"
            f"KANON_SOURCE_beta_REF=main\n"
            f"KANON_SOURCE_beta_PATH={_MANIFEST_NAME}\n"
            f"KANON_SOURCE_beta_NAME=beta\n"
            f"KANON_SOURCE_beta_GITBASE={org_beta}\n"
        )

        install(kanonenv.resolve(), lock_file_path=workspace / ".kanon.lock")

        alpha_text = _substituted_manifest_path("alpha").read_text(encoding="utf-8")
        beta_text = _substituted_manifest_path("beta").read_text(encoding="utf-8")

        assert f'fetch="{org_alpha}/repos"' in alpha_text, f"alpha manifest must use {org_alpha!r}; got {alpha_text!r}"
        assert f'fetch="{org_beta}/repos"' in beta_text, f"beta manifest must use {org_beta!r}; got {beta_text!r}"
        assert org_beta not in alpha_text, f"alpha manifest must not leak beta's org base; got {alpha_text!r}"
        assert org_alpha not in beta_text, f"beta manifest must not leak alpha's org base; got {beta_text!r}"


@pytest.mark.integration
class TestBuildSourceEnvsubstVars:
    """Unit-level contract for the per-source envsubst environment builder."""

    def test_per_source_env_wins_over_global(self) -> None:
        """A source's per-dependency env var overrides a same-named global."""
        base = {"CLAUDE_MARKETPLACES_DIR": "/tmp/mp", "GITBASE": "https://global.example.com"}
        result = build_source_envsubst_vars(base, {"GITBASE": "https://github.com/org-alpha"})
        assert result["GITBASE"] == "https://github.com/org-alpha"
        assert result["CLAUDE_MARKETPLACES_DIR"] == "/tmp/mp"
        assert base["GITBASE"] == "https://global.example.com", "the base mapping must not be mutated"

    def test_empty_source_env_returns_base_copy(self) -> None:
        """An empty per-source env map leaves the base variables unchanged.

        A source whose manifest references no ${VAR} declares no env var, so the
        envsubst environment is exactly the shared base (no fail-fast).
        """
        base = {"CLAUDE_MARKETPLACES_DIR": "/tmp/mp"}
        result = build_source_envsubst_vars(base, {})
        assert result == {"CLAUDE_MARKETPLACES_DIR": "/tmp/mp"}
        assert result is not base, "the base mapping must not be returned by reference"

    def test_custom_per_source_var_is_injected(self) -> None:
        """A non-GITBASE per-dependency env var is injected verbatim."""
        result = build_source_envsubst_vars({}, {"MYBASE": "https://example.com/custom"})
        assert result == {"MYBASE": "https://example.com/custom"}
