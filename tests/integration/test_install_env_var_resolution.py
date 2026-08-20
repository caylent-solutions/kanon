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

import xml.etree.ElementTree as ET

from kanon_cli.constants import UNFILLED_VAR_SENTINEL
from kanon_cli.core.install import _UNRESOLVED_PLACEHOLDER_PATTERN, _is_unfilled_source_var
from kanon_cli.core.manifest_vars import (
    functional_vars_in_manifest_files,
    MalformedManifestVarError,
    _vars_in_attributes,
)


from kanon_cli.constants import KANON_ALLOW_INSECURE_REMOTES
from kanon_cli.core.install import (
    _RefResolution,
    UnresolvedManifestVarError,
    compute_project_address,
    install,
)


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

_LINKFILE_VAR_MANIFEST = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="origin" fetch="https://example.com/repos" />
  <default revision="main" remote="origin" />
  <project name="pkg" path="pkg">
    <linkfile src="rules" dest="${KITROOT}/.claude/rules" />
  </project>
</manifest>
"""

_PROSE_VAR_MANIFEST = """\
<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <!-- Set ${GITBASE} to your org base, e.g. https://github.com/caylent -->
  <remote name="origin" fetch="${GITBASE}/repos" />
  <default revision="main" remote="origin" />
  <project name="pkg" path="pkg">
    <description><![CDATA[Override ${HOME} to relocate the cache.]]></description>
  </project>
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


def _substituted_manifest_path(kanonenv: pathlib.Path, alias: str) -> pathlib.Path:
    """Return the post-envsubst manifest path under the isolated KANON_HOME store."""
    store_base = pathlib.Path(os.environ["KANON_HOME"]) / "store"
    project_address = compute_project_address(kanonenv)
    return store_base / ".kanon-data" / "sources" / project_address / alias / ".repo" / "manifests" / _MANIFEST_NAME


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

        manifest_text = _substituted_manifest_path(kanonenv, "noenv").read_text(encoding="utf-8")
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

        manifest_text = _substituted_manifest_path(kanonenv, "custom").read_text(encoding="utf-8")
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

    def test_linkfile_dest_var_install_fails_cleanly_when_value_missing(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        _no_network_sync,
    ) -> None:
        """Install of a manifest whose ONLY ${VAR} is a <linkfile dest> fails fast.

        ``repo sync`` materializes ``<linkfile dest>`` on disk, so an unresolved
        ${VAR} there is not prose: it produces a literal ``${KITROOT}`` directory
        in the store while the consumer's intended destination stays empty.

        Falsifiability: before the fix the guard scanned only each <project>'s OWN
        attributes, so ${KITROOT} was invisible, the repo tool's envsubst merely
        warned, and install exited 0 with the content linked to the wrong path.
        """
        monkeypatch.delenv("GITBASE", raising=False)
        monkeypatch.delenv("KITROOT", raising=False)
        monkeypatch.setenv(KANON_ALLOW_INSECURE_REMOTES, "1")

        repos = tmp_path / "repos"
        repos.mkdir()
        bare = _make_manifest_bare_repo(repos, "linkvar", _LINKFILE_VAR_MANIFEST)

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanonenv = workspace / ".kanon"
        kanonenv.write_text(_block("linkvar", bare))

        with pytest.raises(UnresolvedManifestVarError) as exc_info:
            install(kanonenv.resolve(), lock_file_path=workspace / ".kanon.lock")

        message = str(exc_info.value)
        assert "linkvar" in message, message
        assert "${KITROOT}" in message, message
        assert "KANON_SOURCE_linkvar_KITROOT" in message, message

    def test_linkfile_dest_var_installs_when_value_provided(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        _no_network_sync,
    ) -> None:
        """The same manifest installs cleanly once the linkfile ${VAR} has a value."""
        monkeypatch.delenv("GITBASE", raising=False)
        monkeypatch.delenv("KITROOT", raising=False)
        monkeypatch.setenv(KANON_ALLOW_INSECURE_REMOTES, "1")

        repos = tmp_path / "repos"
        repos.mkdir()
        bare = _make_manifest_bare_repo(repos, "linkvar", _LINKFILE_VAR_MANIFEST)

        project_root = tmp_path / "project-root"
        project_root.mkdir()
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanonenv = workspace / ".kanon"
        kanonenv.write_text(_block("linkvar", bare, env_lines=f"KANON_SOURCE_linkvar_KITROOT={project_root}\n"))

        install(kanonenv.resolve(), lock_file_path=workspace / ".kanon.lock")

        manifest_text = _substituted_manifest_path(kanonenv, "linkvar").read_text(encoding="utf-8")
        assert "${KITROOT}" not in manifest_text, f"${{KITROOT}} must be substituted; got {manifest_text!r}"
        assert f'dest="{project_root}/.claude/rules"' in manifest_text, (
            f"<linkfile dest> must resolve to {project_root!r}; got {manifest_text!r}"
        )

    def test_prose_var_in_comment_and_cdata_is_ignored(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        _no_network_sync,
    ) -> None:
        """A ${VAR} that survives only in an XML comment / CDATA must not fail install.

        Regression for the ef86a2b scope mismatch: the guard scanned the raw
        resolved-manifest TEXT, so a ${GITBASE} in an XML comment and a ${HOME}
        in a <description> CDATA block tripped UnresolvedManifestVarError even
        though the FUNCTIONAL <remote fetch> resolved correctly. The rewritten
        guard scans only functional attribute values, so install must succeed.

        Falsifiability: under the pre-fix text-scan guard, the surviving comment
        ${GITBASE} and CDATA ${HOME} raise UnresolvedManifestVarError and install
        fails; under the fixed functional-scope guard install exits 0.
        """
        monkeypatch.delenv("GITBASE", raising=False)
        monkeypatch.delenv("HOME", raising=False)
        monkeypatch.setenv(KANON_ALLOW_INSECURE_REMOTES, "1")

        repos = tmp_path / "repos"
        repos.mkdir()
        bare = _make_manifest_bare_repo(repos, "prose", _PROSE_VAR_MANIFEST)

        org_base = "https://github.com/caylent"
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanonenv = workspace / ".kanon"
        kanonenv.write_text(_block("prose", bare, env_lines=f"KANON_SOURCE_prose_GITBASE={org_base}\n"))

        install(kanonenv.resolve(), lock_file_path=workspace / ".kanon.lock")

        manifest_text = _substituted_manifest_path(kanonenv, "prose").read_text(encoding="utf-8")
        assert f'fetch="{org_base}/repos"' in manifest_text, (
            f"functional <remote fetch> must resolve to {org_base!r}; got {manifest_text!r}"
        )

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

        gb_text = _substituted_manifest_path(kanonenv, "gb").read_text(encoding="utf-8")
        plain_text = _substituted_manifest_path(kanonenv, "plain").read_text(encoding="utf-8")
        assert f'fetch="{org_base}/repos"' in gb_text, f"gb manifest must use {org_base!r}; got {gb_text!r}"
        assert "${GITBASE}" not in gb_text, f"${{GITBASE}} must be substituted; got {gb_text!r}"
        assert "${" not in plain_text, f"no-var manifest must carry no placeholder; got {plain_text!r}"


@pytest.mark.integration
class TestManifestVarGrammar:
    """The detector must cover exactly what ``repo envsubst`` expands.

    ``repo envsubst`` substitutes through :func:`os.path.expandvars`, which
    expands ``$VAR`` and ``${VAR}`` alike. A spelling the substituter expands but
    the detector misses is invisible to both ``kanon add`` and the install-time
    guard, so install exits 0 with the variable unset and delivers nothing.
    """

    def test_unbraced_var_in_linkfile_dest_is_detected(self) -> None:
        """A bare ``$VAR`` in a dest is detected, not only the braced spelling."""
        element = ET.fromstring('<linkfile src="rules" dest="$KITROOT/.claude/rules" />')
        assert _vars_in_attributes(element) == {"KITROOT"}

    def test_braced_and_unbraced_agree(self) -> None:
        """Both spellings yield the same name, because envsubst treats them alike."""
        braced = _vars_in_attributes(ET.fromstring('<linkfile src="s" dest="${V}/x" />'))
        bare = _vars_in_attributes(ET.fromstring('<linkfile src="s" dest="$V/x" />'))
        assert braced == bare == {"V"}

    @pytest.mark.parametrize(
        "dest",
        ["${VAR:-default}/x", "${ VAR }/x", "${A${B}}/x", "${MY-VAR}/x"],
        ids=["default-expansion", "padded", "nested", "hyphen"],
    )
    def test_malformed_reference_is_rejected(self, dest: str) -> None:
        """A body envsubst can never resolve fails at detection.

        Left to pass, it becomes a ``.kanon`` key that no value can satisfy, so
        the source is permanently uninstallable however many times the operator
        follows the remediation.
        """
        element = ET.fromstring(f'<linkfile src="s" dest="{dest}" />')
        with pytest.raises(MalformedManifestVarError, match="not a variable reference"):
            _vars_in_attributes(element)

    @pytest.mark.parametrize("dest", ["${V", "${}", "plain/path"], ids=["unclosed", "empty", "literal"])
    def test_non_references_are_ignored(self, dest: str) -> None:
        """Text envsubst leaves alone is not treated as a variable."""
        element = ET.fromstring(f'<linkfile src="s" dest="{dest}" />')
        assert _vars_in_attributes(element) == set()


@pytest.mark.integration
class TestUnfilledSourceVariable:
    """An unfilled per-source variable must not reach ``repo sync``.

    ``kanon add`` writes one line per variable for the operator to fill in. An
    empty value substitutes as the empty string, so ``dest="${VAR}/.claude/rules"``
    collapses to ``/.claude/rules`` -- an absolute path at the filesystem root --
    while leaving no placeholder for the guard to catch.
    """

    def test_empty_per_source_value_is_flagged_as_unfilled(self) -> None:
        assert _is_unfilled_source_var("KANON_SOURCE_pkg_KITROOT", "")

    def test_whitespace_only_value_is_flagged_as_unfilled(self) -> None:
        assert _is_unfilled_source_var("KANON_SOURCE_pkg_KITROOT", "   ")

    def test_filled_value_is_accepted(self) -> None:
        assert not _is_unfilled_source_var("KANON_SOURCE_pkg_KITROOT", "/opt/kit")

    @pytest.mark.parametrize("suffix", ["URL", "REF", "PATH", "NAME"])
    def test_structural_suffixes_are_not_flagged(self, suffix: str) -> None:
        """Structural keys are validated elsewhere; ``_PATH`` is legitimately empty."""
        assert not _is_unfilled_source_var(f"KANON_SOURCE_pkg_{suffix}", "")

    def test_sentinel_is_caught_by_the_placeholder_scanner(self) -> None:
        """The value ``kanon add`` writes is one the install-time scanner rejects."""
        assert _UNRESOLVED_PLACEHOLDER_PATTERN.search(UNFILLED_VAR_SENTINEL) is not None


@pytest.mark.integration
class TestFunctionalElementCoverage:
    """Every manifest position `repo` consumes must be visible to detection.

    Detection walked `<project>` and the `<remote>` elements projects reference.
    A `${VAR}` anywhere else was substituted by `repo envsubst` but announced by
    nothing, so `kanon add` wrote no line for it and the install-time guard saw
    nothing to complain about -- the same silent no-delivery as issue #95, in a
    different element.
    """

    def _detect(self, tmp_path: pathlib.Path, xml: str) -> set[str]:
        manifest = tmp_path / "m.xml"
        manifest.write_text(xml, encoding="utf-8")
        return functional_vars_in_manifest_files([manifest])

    def test_default_revision_is_detected(self, tmp_path: pathlib.Path) -> None:
        """`<default revision>` decides which commit every unpinned project checks out."""
        assert self._detect(
            tmp_path,
            '<manifest><default remote="o" revision="${DEFREV}"/><project name="p" path="p"/></manifest>',
        ) == {"DEFREV"}

    def test_nested_project_children_are_detected(self, tmp_path: pathlib.Path) -> None:
        """A sub-project's delivery destination is as functional as its parent's."""
        assert self._detect(
            tmp_path,
            '<manifest><project name="p" path="p">'
            '<project name="s" path="s"><linkfile src="a" dest="${SUBROOT}/x"/></project>'
            "</project></manifest>",
        ) == {"SUBROOT"}

    @pytest.mark.parametrize(
        ("xml", "expected"),
        [
            ('<manifest><extend-project name="p" dest-path="${EXTDEST}"/></manifest>', "EXTDEST"),
            ('<manifest><remove-project name="${GONE}"/></manifest>', "GONE"),
            ('<manifest><manifest-server url="${MSURL}"/></manifest>', "MSURL"),
            ('<manifest><superproject name="s" remote="o" revision="${SUPERREV}"/></manifest>', "SUPERREV"),
            ('<manifest><contactinfo bugurl="${BUGURL}"/></manifest>', "BUGURL"),
            ('<manifest><repo-hooks in-project="${HOOKPROJ}" enabled-list="p"/></manifest>', "HOOKPROJ"),
        ],
        ids=["extend-project", "remove-project", "manifest-server", "superproject", "contactinfo", "repo-hooks"],
    )
    def test_remaining_functional_elements_are_detected(self, tmp_path: pathlib.Path, xml: str, expected: str) -> None:
        assert expected in self._detect(tmp_path, xml)

    def test_a_remote_no_project_references_is_still_ignored(self, tmp_path: pathlib.Path) -> None:
        """Scoping remotes to referenced ones is deliberate, not an oversight.

        Detecting a variable in an unused `<remote>` would make `kanon add` write a
        line for it, and an unfilled line now fails the install -- so a manifest
        carrying an unused remote would stop installing altogether.
        """
        detected = self._detect(
            tmp_path,
            "<manifest>"
            '<remote name="used" fetch="${USED}"/>'
            '<remote name="unused" fetch="${UNUSED}"/>'
            '<project name="p" path="p" remote="used"/>'
            "</manifest>",
        )
        assert detected == {"USED"}, f"expected only the referenced remote's variable, got {detected!r}"

    def test_a_remote_referenced_only_by_superproject_is_detected(self, tmp_path: pathlib.Path) -> None:
        """A remote is live if anything references it, not only a `<project>`."""
        detected = self._detect(
            tmp_path,
            "<manifest>"
            '<remote name="sup" fetch="${SUPFETCH}"/>'
            '<superproject name="s" remote="sup" revision="main"/>'
            "</manifest>",
        )
        assert "SUPFETCH" in detected


@pytest.mark.integration
class TestPlainReinstallReResolves:
    """A changed variable takes effect on a plain `kanon install`.

    The `.repo/manifests` reset moved out of the `--refresh-lock` branch to run
    before *every* `repo init`. That is the entire justification for the move: a
    keyed workspace belongs to one project, so resetting is always safe, and it
    lets envsubst re-resolve when a variable changed since the last install.

    Nothing asserted it. Moving the call back inside `if _is_reresolve:` would
    have broken no test, so the behaviour this branch introduced was unprotected.

    The shared autouse mock returns a placeholder SHA. The second install pins it
    from the lockfile and hands it to a real `repo init`, which cannot find it, so
    this test overrides the mock with the bare repo's actual HEAD -- keeping every
    other part of the install real, which is the point.
    """

    def test_changed_variable_re_resolves_without_refresh_lock(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        _no_network_sync,
    ) -> None:
        monkeypatch.delenv("GITBASE", raising=False)
        monkeypatch.delenv("KITROOT", raising=False)
        monkeypatch.setenv(KANON_ALLOW_INSECURE_REMOTES, "1")

        repos = tmp_path / "repos"
        repos.mkdir()
        bare = _make_manifest_bare_repo(repos, "linkvar", _LINKFILE_VAR_MANIFEST)

        real_head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(bare), capture_output=True, text=True, check=True
        ).stdout.strip()
        monkeypatch.setattr(
            "kanon_cli.core.install._resolve_ref_to_sha",
            lambda *args, **kwargs: _RefResolution(sha=real_head, resolved_ref="refs/heads/main"),
        )

        first_root = tmp_path / "first-root"
        second_root = tmp_path / "second-root"
        for root in (first_root, second_root):
            root.mkdir()

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        kanonenv = workspace / ".kanon"
        lock = workspace / ".kanon.lock"

        kanonenv.write_text(_block("linkvar", bare, env_lines=f"KANON_SOURCE_linkvar_KITROOT={first_root}\n"))
        install(kanonenv.resolve(), lock_file_path=lock)
        assert f'dest="{first_root}/.claude/rules"' in _substituted_manifest_path(kanonenv, "linkvar").read_text(
            encoding="utf-8"
        )

        kanonenv.write_text(_block("linkvar", bare, env_lines=f"KANON_SOURCE_linkvar_KITROOT={second_root}\n"))
        install(kanonenv.resolve(), lock_file_path=lock)

        substituted = _substituted_manifest_path(kanonenv, "linkvar").read_text(encoding="utf-8")
        assert f'dest="{second_root}/.claude/rules"' in substituted, (
            "a plain 'kanon install' did not re-resolve the changed variable; the manifests "
            f"reset must run before every repo init, not only under --refresh-lock. Got: {substituted!r}"
        )
        assert str(first_root) not in substituted, "the previous substitution survived the re-install"
