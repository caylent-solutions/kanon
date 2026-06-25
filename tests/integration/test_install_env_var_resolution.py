"""Integration tests: install injects per-dependency env vars and hard-fails on unresolved ${VAR}.

``install`` injects each source's open per-dependency env-var map
(``source_data["env"]``) into THAT source's repo envsubst, then performs a
kanon-side scan of the resolved manifest (and its ``<include>`` chain): if any
``${VAR}`` remains after envsubst it fails cleanly (the repo tool only warns and
exits 0). These tests exercise the real ``install()`` API against real bare git
manifest repos with a real ``repo init`` + ``repo envsubst`` (``repo sync`` is
stubbed so no network fetch runs while the substitution + scan path executes).

Spec reference: specs/kanon-refinements.md Section 5.1 (optional per-dependency
env vars), Section 4.2 (install injection + unresolved-var hard fail).
"""

import os
import pathlib
import subprocess

import pytest

from kanon_cli.constants import KANON_ALLOW_INSECURE_REMOTES
from kanon_cli.core.install import UnresolvedManifestVarError, install


_GIT_USER_NAME = "Env Var Install Test"
_GIT_USER_EMAIL = "env-var-install@example.com"
_MANIFEST_NAME = "remote.xml"

_NO_VAR_MANIFEST = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/repos" />
  <default revision="main" remote="origin" />
  <project name="pkg" path="pkg" />
</manifest>
"""

_GITBASE_MANIFEST = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${GITBASE}/repos" />
  <default revision="main" remote="origin" />
  <project name="pkg" path="pkg" />
</manifest>
"""

_CUSTOM_VAR_MANIFEST = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="${MYBASE}/repos" />
  <default revision="main" remote="origin" />
  <project name="pkg" path="pkg" />
</manifest>
"""


def _git(args: list[str], cwd: pathlib.Path) -> None:
    """Run a git command in cwd, raising RuntimeError on non-zero exit."""
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {args!r} failed in {cwd!r}: stdout={result.stdout!r} stderr={result.stderr!r}")


def _make_manifest_bare_repo(base: pathlib.Path, slug: str, manifest: str) -> pathlib.Path:
    """Create a bare git repo containing a remote.xml with the given content."""
    work_dir = base / f"{slug}-work"
    work_dir.mkdir(parents=True)
    _git(["init", "-b", "main"], cwd=work_dir)
    _git(["config", "user.name", _GIT_USER_NAME], cwd=work_dir)
    _git(["config", "user.email", _GIT_USER_EMAIL], cwd=work_dir)
    (work_dir / _MANIFEST_NAME).write_text(manifest, encoding="utf-8")
    _git(["add", _MANIFEST_NAME], cwd=work_dir)
    _git(["commit", "-m", "manifest"], cwd=work_dir)

    bare_dir = base / f"{slug}-bare"
    _git(["clone", "--bare", str(work_dir), str(bare_dir)], cwd=base)
    return bare_dir


def _substituted_manifest_path(alias: str) -> pathlib.Path:
    """Return the post-envsubst manifest path under the isolated KANON_HOME store."""
    store_base = pathlib.Path(os.environ["KANON_HOME"]) / "store"
    return store_base / ".kanon-data" / "sources" / alias / ".repo" / "manifests" / _MANIFEST_NAME


@pytest.fixture
def _no_network_sync(monkeypatch: pytest.MonkeyPatch):
    """Stub repo sync so only repo init + repo envsubst run (no network fetch)."""
    monkeypatch.setattr("kanon_cli.repo.repo_sync", lambda *args, **kwargs: None)


def _block(alias: str, bare: pathlib.Path, env_lines: str = "") -> str:
    """Build a structural .kanon block for one source, plus optional env-var lines."""
    return (
        f"KANON_SOURCE_{alias}_URL=file://{bare}\n"
        f"KANON_SOURCE_{alias}_REF=main\n"
        f"KANON_SOURCE_{alias}_PATH={_MANIFEST_NAME}\n"
        f"KANON_SOURCE_{alias}_NAME={alias}\n"
    ) + env_lines


@pytest.mark.integration
class TestInstallEnvVarResolution:
    """install injects per-dependency env vars and hard-fails on an unresolved ${VAR}."""

    def test_no_var_source_installs_without_env_line(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        _no_network_sync,
    ) -> None:
        """Case (a): a no-${VAR} manifest installs cleanly with no env-var line."""
        monkeypatch.delenv("GITBASE", raising=False)
        monkeypatch.setenv(KANON_ALLOW_INSECURE_REMOTES, "1")

        repos = tmp_path / "repos"
        repos.mkdir()
        bare = _make_manifest_bare_repo(repos, "noenv", _NO_VAR_MANIFEST)

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanonenv = workspace / ".kanon"
        kanonenv.write_text(_block("noenv", bare))

        install(kanonenv.resolve(), lock_file_path=workspace / ".kanon.lock")

        manifest_text = _substituted_manifest_path("noenv").read_text(encoding="utf-8")
        assert "${" not in manifest_text, f"no placeholder expected; got {manifest_text!r}"

    def test_custom_var_resolves_when_value_provided(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        _no_network_sync,
    ) -> None:
        """Case (b): a custom ${MYBASE} resolves when KANON_SOURCE_<alias>_MYBASE is set."""
        monkeypatch.delenv("GITBASE", raising=False)
        monkeypatch.delenv("MYBASE", raising=False)
        monkeypatch.setenv(KANON_ALLOW_INSECURE_REMOTES, "1")

        repos = tmp_path / "repos"
        repos.mkdir()
        bare = _make_manifest_bare_repo(repos, "custom", _CUSTOM_VAR_MANIFEST)

        org_base = "https://github.com/custom-org"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanonenv = workspace / ".kanon"
        kanonenv.write_text(_block("custom", bare, env_lines=f"KANON_SOURCE_custom_MYBASE={org_base}\n"))

        install(kanonenv.resolve(), lock_file_path=workspace / ".kanon.lock")

        manifest_text = _substituted_manifest_path("custom").read_text(encoding="utf-8")
        assert "${MYBASE}" not in manifest_text, f"${{MYBASE}} must be substituted; got {manifest_text!r}"
        assert f'fetch="{org_base}/repos"' in manifest_text, f"manifest must use {org_base!r}; got {manifest_text!r}"

    def test_custom_var_install_fails_cleanly_when_value_missing(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        _no_network_sync,
    ) -> None:
        """Case (b): install of a ${MYBASE} manifest WITHOUT the value fails cleanly.

        Falsifiability: if the kanon-side post-envsubst scan did not run, install
        would proceed (the repo tool only warns), so no error would be raised.
        """
        monkeypatch.delenv("GITBASE", raising=False)
        monkeypatch.delenv("MYBASE", raising=False)
        monkeypatch.setenv(KANON_ALLOW_INSECURE_REMOTES, "1")

        repos = tmp_path / "repos"
        repos.mkdir()
        bare = _make_manifest_bare_repo(repos, "custom", _CUSTOM_VAR_MANIFEST)

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanonenv = workspace / ".kanon"
        kanonenv.write_text(_block("custom", bare))

        with pytest.raises(UnresolvedManifestVarError) as exc_info:
            install(kanonenv.resolve(), lock_file_path=workspace / ".kanon.lock")

        message = str(exc_info.value)
        assert "custom" in message, message
        assert "${MYBASE}" in message, message
        assert "KANON_SOURCE_custom_MYBASE" in message, message

    def test_mixed_gitbase_and_no_var_sources_install(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        _no_network_sync,
    ) -> None:
        """Case (d): a .kanon with one ${GITBASE} source + one no-var source installs both."""
        monkeypatch.delenv("GITBASE", raising=False)
        monkeypatch.setenv(KANON_ALLOW_INSECURE_REMOTES, "1")

        repos = tmp_path / "repos"
        repos.mkdir()
        bare_gb = _make_manifest_bare_repo(repos, "gb", _GITBASE_MANIFEST)
        bare_plain = _make_manifest_bare_repo(repos, "plain", _NO_VAR_MANIFEST)

        org_base = "https://github.com/mixed-org"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanonenv = workspace / ".kanon"
        kanonenv.write_text(
            _block("gb", bare_gb, env_lines=f"KANON_SOURCE_gb_GITBASE={org_base}\n") + _block("plain", bare_plain)
        )

        install(kanonenv.resolve(), lock_file_path=workspace / ".kanon.lock")

        gb_text = _substituted_manifest_path("gb").read_text(encoding="utf-8")
        plain_text = _substituted_manifest_path("plain").read_text(encoding="utf-8")
        assert f'fetch="{org_base}/repos"' in gb_text, f"gb manifest must use {org_base!r}; got {gb_text!r}"
        assert "${GITBASE}" not in gb_text, f"${{GITBASE}} must be substituted; got {gb_text!r}"
        assert "${" not in plain_text, f"no-var manifest must carry no placeholder; got {plain_text!r}"
