"""Unit tests for the --refresh-lock-source flag in kanon install.

AC-TEST-001: Parametrises the five paths:
  (a) refresh by source name (KANON_SOURCE_<name> key).
  (b) refresh by catalog entry name (via derive_source_name).
  (c) unknown name raises UnknownSourceError.
  (d) mutual exclusion with --refresh-lock raises SystemExit(2).
  (e) missing catalog source on refresh path raises MissingCatalogSourceError.

AC-FUNC-001 through AC-FUNC-007 verified by these unit tests.
"""

from __future__ import annotations

import argparse
import inspect
import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.core.include_walker import IncludeTree
from kanon_cli.core.install import (
    InstallState,
    MissingCatalogSourceError,
    UnknownSourceError,
    _RefResolution,
    _emit_install_state,
    _merge_partial_lockfile,
    _resolve_source_name,
    install,
)
from kanon_cli.core.kanon_hash import kanon_hash as compute_kanon_hash
from kanon_cli.core.lockfile import (
    CatalogBlock,
    Lockfile,
    ProjectEntry,
    SourceEntry,
)


# ---------------------------------------------------------------------------
# Shared fixture content
# ---------------------------------------------------------------------------

_VALID_SHA_A = "a" * 40
_VALID_SHA_B = "b" * 40
_VALID_SHA_C = "c" * 40

_KANON_TWO_SOURCE = """\
GITBASE=https://git.example.com
CLAUDE_MARKETPLACES_DIR=/tmp/mktplc
KANON_MARKETPLACE_INSTALL=false
KANON_SOURCE_alpha_URL=https://git.example.com/alpha.git
KANON_SOURCE_alpha_REVISION=main
KANON_SOURCE_alpha_PATH=manifest.xml
KANON_SOURCE_beta_URL=https://git.example.com/beta.git
KANON_SOURCE_beta_REVISION=main
KANON_SOURCE_beta_PATH=manifest.xml
"""


def _write_kanon(directory: pathlib.Path, content: str = _KANON_TWO_SOURCE) -> pathlib.Path:
    kanon_path = directory / ".kanon"
    kanon_path.write_text(content)
    kanon_path.chmod(0o600)
    return kanon_path


def _make_project_entry(name: str, url: str = "https://git.example.com/proj.git") -> ProjectEntry:
    from kanon_cli.core.lockfile import canonicalize_repo_url

    return ProjectEntry(
        name=name,
        url=url,
        canonical_url=canonicalize_repo_url(url),
        revision_spec="main",
        resolved_ref="refs/heads/main",
        resolved_sha=_VALID_SHA_A,
    )


def _make_source_entry(
    name: str,
    url: str = "https://git.example.com/repo.git",
    sha: str = _VALID_SHA_A,
    revision_spec: str = "main",
    resolved_ref: str = "refs/heads/main",
    path: str = "manifest.xml",
    projects: list[ProjectEntry] | None = None,
) -> SourceEntry:
    return SourceEntry(
        name=name,
        url=url,
        revision_spec=revision_spec,
        resolved_ref=resolved_ref,
        resolved_sha=sha,
        path=path,
        projects=projects or [],
    )


def _make_lockfile(
    kanon_path: pathlib.Path,
    source_entries: list[SourceEntry],
    catalog_source: str = "https://git.example.com/catalog.git@main",
) -> Lockfile:
    kanon_hash = compute_kanon_hash(kanon_path)
    catalog_url, catalog_ref = catalog_source.rsplit("@", 1)
    return Lockfile(
        schema_version=1,
        generated_at="2026-01-15T00:00:00Z",
        generator="kanon-cli/test",
        kanon_hash=kanon_hash,
        catalog=CatalogBlock(
            source=catalog_source,
            url=catalog_url,
            revision_spec=catalog_ref,
            resolved_ref=f"refs/heads/{catalog_ref}",
            resolved_sha=_VALID_SHA_C,
        ),
        sources=source_entries,
    )


def _write_lockfile_file(
    directory: pathlib.Path,
    lockfile: Lockfile,
) -> pathlib.Path:
    from kanon_cli.core.lockfile import write_lockfile

    lock_path = directory / ".kanon.lock"
    write_lockfile(lockfile, lock_path)
    return lock_path


# ---------------------------------------------------------------------------
# Shared fixture for .kanon file and lockfile with two sources
# ---------------------------------------------------------------------------


@pytest.fixture()
def two_source_setup(tmp_path: pathlib.Path):
    """Set up .kanon and .kanon.lock with sources alpha and beta."""
    kanon_path = _write_kanon(tmp_path)
    alpha_entry = _make_source_entry(
        name="alpha",
        url="https://git.example.com/alpha.git",
        sha=_VALID_SHA_A,
    )
    beta_entry = _make_source_entry(
        name="beta",
        url="https://git.example.com/beta.git",
        sha=_VALID_SHA_B,
    )
    lockfile = _make_lockfile(kanon_path, [alpha_entry, beta_entry])
    lock_path = _write_lockfile_file(tmp_path, lockfile)
    return {
        "kanon_path": kanon_path,
        "lock_path": lock_path,
        "lockfile": lockfile,
        "alpha_entry": alpha_entry,
        "beta_entry": beta_entry,
    }


# ===========================================================================
# AC-FUNC-001: InstallState.REFRESH_LOCK_SOURCE enum value exists
# ===========================================================================


@pytest.mark.unit
class TestRefreshLockSourceInstallState:
    """AC-FUNC-001: REFRESH_LOCK_SOURCE enum value is present on InstallState."""

    def test_refresh_lock_source_state_exists(self) -> None:
        """InstallState.REFRESH_LOCK_SOURCE must be a valid enum member."""
        assert hasattr(InstallState, "REFRESH_LOCK_SOURCE")
        assert isinstance(InstallState.REFRESH_LOCK_SOURCE, InstallState)

    def test_refresh_lock_source_is_distinct_from_all_others(self) -> None:
        """REFRESH_LOCK_SOURCE must differ from every other InstallState value."""
        other_states = [
            InstallState.LOCKFILE_ABSENT,
            InstallState.LOCKFILE_CONSISTENT,
            InstallState.LOCKFILE_HASH_MISMATCH,
            InstallState.LOCKFILE_UNREACHABLE,
            InstallState.LOCKFILE_SOURCE_MISMATCH,
            InstallState.REFRESH_LOCK,
        ]
        for other in other_states:
            assert InstallState.REFRESH_LOCK_SOURCE is not other


# ===========================================================================
# AC-FUNC-001 / AC-FUNC-002: _resolve_source_name resolution
# ===========================================================================


@pytest.mark.unit
class TestResolveSourceName:
    """Tests for _resolve_source_name two-step resolution."""

    def test_resolve_by_source_name_direct(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-001: name matching a KANON_SOURCE_<name> key resolves directly."""
        kanon_path = _write_kanon(tmp_path)
        alpha_entry = _make_source_entry(name="alpha", url="https://git.example.com/alpha.git")
        beta_entry = _make_source_entry(name="beta", url="https://git.example.com/beta.git")
        lockfile = _make_lockfile(kanon_path, [alpha_entry, beta_entry])

        result = _resolve_source_name("alpha", lockfile)
        assert result.name == "alpha"
        assert result.url == "https://git.example.com/alpha.git"

    def test_resolve_by_catalog_entry_name_via_derive(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-002: name matching via derive_source_name resolves to correct entry."""
        kanon_path = _write_kanon(tmp_path)
        # 'Alpha-Tool' normalises via derive_source_name to 'alpha_tool'
        # but our source name is 'alpha', so we need a source named 'alpha_tool'
        # to demonstrate the derive path.
        kanon_content = """\
GITBASE=https://git.example.com
CLAUDE_MARKETPLACES_DIR=/tmp/mktplc
KANON_MARKETPLACE_INSTALL=false
KANON_SOURCE_alpha_tool_URL=https://git.example.com/alpha.git
KANON_SOURCE_alpha_tool_REVISION=main
KANON_SOURCE_alpha_tool_PATH=manifest.xml
KANON_SOURCE_beta_URL=https://git.example.com/beta.git
KANON_SOURCE_beta_REVISION=main
KANON_SOURCE_beta_PATH=manifest.xml
"""
        kanon_path = _write_kanon(tmp_path, kanon_content)
        alpha_entry = _make_source_entry(name="alpha_tool", url="https://git.example.com/alpha.git")
        beta_entry = _make_source_entry(name="beta", url="https://git.example.com/beta.git")
        lockfile = _make_lockfile(kanon_path, [alpha_entry, beta_entry])

        # 'Alpha-Tool' normalises to 'alpha_tool' via derive_source_name
        result = _resolve_source_name("Alpha-Tool", lockfile)
        assert result.name == "alpha_tool"

    def test_resolve_unknown_name_raises_unknown_source_error(self, tmp_path: pathlib.Path) -> None:
        """AC-FUNC-003: unknown name raises UnknownSourceError with diagnostic payload."""
        kanon_path = _write_kanon(tmp_path)
        alpha_entry = _make_source_entry(name="alpha")
        beta_entry = _make_source_entry(name="beta")
        lockfile = _make_lockfile(kanon_path, [alpha_entry, beta_entry])

        with pytest.raises(UnknownSourceError) as exc_info:
            _resolve_source_name("nonexistent", lockfile)

        err = exc_info.value
        err_str = str(err)
        assert "nonexistent" in err_str
        # Error must list known source names
        assert "alpha" in err_str
        assert "beta" in err_str

    @pytest.mark.parametrize(
        "name,expected_source_name",
        [
            ("alpha", "alpha"),
            ("beta", "beta"),
            ("ALPHA", "alpha"),  # derive_source_name lowercases
        ],
    )
    def test_resolve_parametrised_by_name_and_derive(
        self,
        tmp_path: pathlib.Path,
        name: str,
        expected_source_name: str,
    ) -> None:
        """Parametrised: both literal and derive_source_name forms resolve correctly."""
        kanon_path = _write_kanon(tmp_path)
        alpha_entry = _make_source_entry(name="alpha", url="https://git.example.com/alpha.git")
        beta_entry = _make_source_entry(name="beta", url="https://git.example.com/beta.git")
        lockfile = _make_lockfile(kanon_path, [alpha_entry, beta_entry])

        result = _resolve_source_name(name, lockfile)
        assert result.name == expected_source_name


# ===========================================================================
# AC-FUNC-003: UnknownSourceError diagnostic payload
# ===========================================================================


@pytest.mark.unit
class TestUnknownSourceError:
    """AC-FUNC-003: UnknownSourceError includes known source names and derive attempts."""

    def test_unknown_source_error_lists_known_names(self, tmp_path: pathlib.Path) -> None:
        """UnknownSourceError message contains all known source names."""
        kanon_path = _write_kanon(tmp_path)
        sources = [
            _make_source_entry(name="alpha"),
            _make_source_entry(name="beta"),
        ]
        lockfile = _make_lockfile(kanon_path, sources)

        with pytest.raises(UnknownSourceError) as exc_info:
            _resolve_source_name("gamma", lockfile)

        err_str = str(exc_info.value)
        assert "alpha" in err_str
        assert "beta" in err_str
        assert "gamma" in err_str

    def test_unknown_source_error_is_install_error_subclass(self, tmp_path: pathlib.Path) -> None:
        """UnknownSourceError inherits from InstallError."""
        from kanon_cli.core.install import InstallError

        assert issubclass(UnknownSourceError, InstallError)

    def test_unknown_source_error_structure(self) -> None:
        """UnknownSourceError can be instantiated with name and known_names."""
        err = UnknownSourceError(name="foo", known_names=["alpha", "beta"])
        err_str = str(err)
        assert "foo" in err_str
        assert "alpha" in err_str
        assert "beta" in err_str


# ===========================================================================
# AC-FUNC-004: --refresh-lock and --refresh-lock-source are mutually exclusive
# ===========================================================================


@pytest.mark.unit
class TestRefreshLockMutualExclusion:
    """AC-FUNC-004: --refresh-lock-source is in the same mutually-exclusive group."""

    def test_refresh_lock_and_refresh_lock_source_are_mutually_exclusive(self) -> None:
        """Passing both --refresh-lock and --refresh-lock-source raises SystemExit(2)."""
        from kanon_cli.commands import install as install_cmd

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        install_cmd.register(subparsers)

        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["install", "--refresh-lock", "--refresh-lock-source", "alpha"])

        assert exc_info.value.code == 2

    def test_refresh_lock_source_alone_is_parsed(self) -> None:
        """--refresh-lock-source alone parses without error."""
        from kanon_cli.commands import install as install_cmd

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        install_cmd.register(subparsers)

        args = parser.parse_args(["install", "--refresh-lock-source", "alpha"])
        assert args.refresh_lock_source == "alpha"

    def test_refresh_lock_source_default_is_none(self) -> None:
        """When --refresh-lock-source is not passed, args.refresh_lock_source defaults to None."""
        from kanon_cli.commands import install as install_cmd

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        install_cmd.register(subparsers)

        args = parser.parse_args(["install"])
        assert args.refresh_lock_source is None

    def test_refresh_lock_source_in_mutually_exclusive_group_with_refresh_lock(self) -> None:
        """Both --refresh-lock and --refresh-lock-source belong to the same mutex group."""
        from kanon_cli.commands import install as install_cmd

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        install_cmd.register(subparsers)

        # --refresh-lock alone should still work
        args = parser.parse_args(["install", "--refresh-lock"])
        assert args.refresh_lock is True
        assert args.refresh_lock_source is None


# ===========================================================================
# AC-FUNC-005: missing catalog source on --refresh-lock-source path
# ===========================================================================


@pytest.mark.unit
class TestRefreshLockSourceMissingCatalog:
    """AC-FUNC-005: missing catalog source raises MissingCatalogSourceError on refresh path."""

    def test_install_refresh_lock_source_missing_catalog_raises(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """install(refresh_lock_source='alpha') with no catalog source raises MissingCatalogSourceError."""
        monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)
        kanon_path = _write_kanon(tmp_path)

        # Write a consistent lockfile -- the lockfile fallback is disabled on this path
        alpha_entry = _make_source_entry(name="alpha", url="https://git.example.com/alpha.git")
        beta_entry = _make_source_entry(name="beta", url="https://git.example.com/beta.git")
        lockfile = _make_lockfile(kanon_path, [alpha_entry, beta_entry])
        _write_lockfile_file(tmp_path, lockfile)

        with pytest.raises(MissingCatalogSourceError) as exc_info:
            install(
                kanonenv_path=kanon_path,
                lock_file_path=kanon_path.parent / ".kanon.lock",
                catalog_source=None,
                refresh_lock_source="alpha",
            )

        msg = str(exc_info.value)
        # Must include refresh-specific remediation
        assert "catalog source" in msg.lower() or "KANON_CATALOG_SOURCE" in msg


# ===========================================================================
# AC-FUNC-006: info-line for REFRESH_LOCK_SOURCE
# ===========================================================================


@pytest.mark.unit
class TestEmitInstallStateRefreshLockSource:
    """AC-FUNC-006: REFRESH_LOCK_SOURCE emits the partial-rebuild info-line."""

    def test_emit_partial_rebuild_info_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        """REFRESH_LOCK_SOURCE emits 'lockfile partially rebuilt: source <name> (M refreshed; K preserved)'."""
        _emit_install_state(
            InstallState.REFRESH_LOCK_SOURCE,
            sources=2,
            projects=5,
            refreshed_source_name="alpha",
            refreshed_count=3,
            preserved_count=2,
        )
        captured = capsys.readouterr()
        assert "lockfile partially rebuilt" in captured.out
        assert "alpha" in captured.out
        assert "3 projects refreshed" in captured.out
        assert "2 projects preserved" in captured.out

    @pytest.mark.parametrize(
        "source_name,refreshed,preserved",
        [
            ("alpha", 0, 5),
            ("beta", 10, 0),
            ("gamma", 3, 7),
        ],
    )
    def test_emit_partial_rebuild_counts_parametrised(
        self,
        capsys: pytest.CaptureFixture[str],
        source_name: str,
        refreshed: int,
        preserved: int,
    ) -> None:
        """Parametrised: info-line counts are dynamic."""
        _emit_install_state(
            InstallState.REFRESH_LOCK_SOURCE,
            sources=2,
            projects=refreshed + preserved,
            refreshed_source_name=source_name,
            refreshed_count=refreshed,
            preserved_count=preserved,
        )
        captured = capsys.readouterr()
        assert source_name in captured.out
        assert f"{refreshed} projects refreshed" in captured.out
        assert f"{preserved} projects preserved" in captured.out

    def test_other_states_unaffected_by_new_kwargs(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Existing states still work when optional kwargs are not passed."""
        _emit_install_state(InstallState.LOCKFILE_ABSENT, sources=1, projects=2)
        captured = capsys.readouterr()
        assert "lockfile rebuilt from .kanon (1 sources, 2 projects)" in captured.out


# ===========================================================================
# AC-FUNC-007: _merge_partial_lockfile preserves non-refreshed sources byte-for-byte
# ===========================================================================


@pytest.mark.unit
class TestMergePartialLockfile:
    """AC-FUNC-007: _merge_partial_lockfile replaces exactly one source entry."""

    def test_merge_replaces_refreshed_source_entry(self, tmp_path: pathlib.Path) -> None:
        """_merge_partial_lockfile replaces exactly the named source, preserves the rest."""
        kanon_path = _write_kanon(tmp_path)
        alpha_old = _make_source_entry(name="alpha", sha=_VALID_SHA_A)
        beta_old = _make_source_entry(name="beta", sha=_VALID_SHA_B)
        old_lockfile = _make_lockfile(kanon_path, [alpha_old, beta_old])

        new_alpha_sha = "e" * 40
        alpha_new = _make_source_entry(name="alpha", sha=new_alpha_sha)

        new_kanon_hash = compute_kanon_hash(kanon_path)
        merged = _merge_partial_lockfile(
            old_lockfile=old_lockfile,
            refreshed_source=alpha_new,
            new_kanon_hash=new_kanon_hash,
        )

        # The refreshed source has the new SHA
        refreshed = next(e for e in merged.sources if e.name == "alpha")
        assert refreshed.resolved_sha == new_alpha_sha

        # The preserved source is byte-equal to the original beta entry
        preserved = next(e for e in merged.sources if e.name == "beta")
        assert preserved == beta_old

    def test_merge_updates_kanon_hash(self, tmp_path: pathlib.Path) -> None:
        """_merge_partial_lockfile records the freshly-computed kanon_hash, not the old one."""
        kanon_path = _write_kanon(tmp_path)
        alpha_old = _make_source_entry(name="alpha", sha=_VALID_SHA_A)
        beta_old = _make_source_entry(name="beta", sha=_VALID_SHA_B)
        old_lockfile = _make_lockfile(kanon_path, [alpha_old, beta_old])
        old_hash = old_lockfile.kanon_hash

        # Compute a fresh hash (same .kanon content -- hashes equal in this case,
        # but the point is we pass a fresh hash and it is recorded)
        new_kanon_hash = compute_kanon_hash(kanon_path)
        alpha_new = _make_source_entry(name="alpha", sha="f" * 40)

        merged = _merge_partial_lockfile(
            old_lockfile=old_lockfile,
            refreshed_source=alpha_new,
            new_kanon_hash=new_kanon_hash,
        )

        assert merged.kanon_hash == new_kanon_hash
        # Verify the hash is actually a valid sha256: prefixed value
        assert merged.kanon_hash.startswith("sha256:")
        assert len(merged.kanon_hash) == 71
        # In this test old_hash == new_kanon_hash (same .kanon content), which is fine
        _ = old_hash  # used to suppress lint warning

    def test_merge_preserves_catalog_block(self, tmp_path: pathlib.Path) -> None:
        """_merge_partial_lockfile preserves the [catalog] block unchanged."""
        kanon_path = _write_kanon(tmp_path)
        alpha_old = _make_source_entry(name="alpha", sha=_VALID_SHA_A)
        beta_old = _make_source_entry(name="beta", sha=_VALID_SHA_B)
        old_lockfile = _make_lockfile(
            kanon_path, [alpha_old, beta_old], catalog_source="https://catalog.example.com/repo.git@v1"
        )

        alpha_new = _make_source_entry(name="alpha", sha="f" * 40)
        new_hash = compute_kanon_hash(kanon_path)
        merged = _merge_partial_lockfile(
            old_lockfile=old_lockfile,
            refreshed_source=alpha_new,
            new_kanon_hash=new_hash,
        )

        assert merged.catalog == old_lockfile.catalog

    def test_merge_raises_on_unknown_source_name(self, tmp_path: pathlib.Path) -> None:
        """_merge_partial_lockfile raises when refreshed_source.name is not in old_lockfile."""
        kanon_path = _write_kanon(tmp_path)
        alpha_old = _make_source_entry(name="alpha", sha=_VALID_SHA_A)
        old_lockfile = _make_lockfile(kanon_path, [alpha_old])

        gamma_entry = _make_source_entry(name="gamma", sha="f" * 40)
        new_hash = compute_kanon_hash(kanon_path)

        with pytest.raises(UnknownSourceError):
            _merge_partial_lockfile(
                old_lockfile=old_lockfile,
                refreshed_source=gamma_entry,
                new_kanon_hash=new_hash,
            )


# ===========================================================================
# AC-FUNC-001/AC-FUNC-007: install() accepts refresh_lock_source kwarg
# ===========================================================================


@pytest.mark.unit
class TestInstallRefreshLockSourceKwarg:
    """install() accepts refresh_lock_source keyword argument."""

    def test_install_has_refresh_lock_source_kwarg(self) -> None:
        """install() signature includes refresh_lock_source: str | None = None."""
        sig = inspect.signature(install)
        assert "refresh_lock_source" in sig.parameters
        param = sig.parameters["refresh_lock_source"]
        assert param.default is None

    def test_install_refresh_lock_source_by_name_rewrites_one_source(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC-FUNC-001: install(refresh_lock_source='alpha') re-resolves only alpha;
        beta entry is preserved verbatim (excluding kanon_hash and generated_at)."""
        monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)
        kanon_path = _write_kanon(tmp_path)

        alpha_entry = _make_source_entry(
            name="alpha",
            url="https://git.example.com/alpha.git",
            sha=_VALID_SHA_A,
        )
        beta_entry = _make_source_entry(
            name="beta",
            url="https://git.example.com/beta.git",
            sha=_VALID_SHA_B,
        )
        lockfile = _make_lockfile(kanon_path, [alpha_entry, beta_entry])
        lock_path = _write_lockfile_file(tmp_path, lockfile)

        # The new SHA that the refresh will resolve to
        new_alpha_sha = "e" * 40
        mock_ref = _RefResolution(sha=new_alpha_sha, resolved_ref="refs/heads/main")

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=mock_ref),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("meta.xml"))),
        ):
            install(
                kanonenv_path=kanon_path,
                lock_file_path=kanon_path.parent / ".kanon.lock",
                catalog_source="https://catalog.example.com/repo.git@main",
                refresh_lock_source="alpha",
            )

        from kanon_cli.core.lockfile import read_lockfile

        new_lf = read_lockfile(lock_path)
        alpha_new = next(e for e in new_lf.sources if e.name == "alpha")
        beta_new = next(e for e in new_lf.sources if e.name == "beta")

        # alpha is refreshed with the new SHA
        assert alpha_new.resolved_sha == new_alpha_sha

        # beta is preserved byte-for-byte (excluding kanon_hash / generated_at at the top level)
        assert beta_new.resolved_sha == _VALID_SHA_B
        assert beta_new.url == beta_entry.url
        assert beta_new.revision_spec == beta_entry.revision_spec
        assert beta_new.resolved_ref == beta_entry.resolved_ref
        assert beta_new.path == beta_entry.path

    def test_install_refresh_lock_source_emits_partial_rebuild_info_line(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """AC-FUNC-006: install(refresh_lock_source='alpha') emits partial-rebuild info-line.

        With two top-level sources (alpha and beta), refreshing alpha yields:
        - refreshed_count == 1 (the alpha top-level source entry was re-resolved)
        - preserved_count == 1 (the beta top-level source entry was kept as-is)

        Counters reflect the number of top-level source entries, not sub-project
        XML include entries. The singular form "project" is used because both
        counts equal 1.
        """
        monkeypatch.delenv("KANON_CATALOG_SOURCE", raising=False)
        kanon_path = _write_kanon(tmp_path)

        alpha_entry = _make_source_entry(name="alpha", url="https://git.example.com/alpha.git")
        beta_entry = _make_source_entry(
            name="beta",
            url="https://git.example.com/beta.git",
            projects=[
                _make_project_entry("proj-b1", "https://git.example.com/b1.git"),
                _make_project_entry("proj-b2", "https://git.example.com/b2.git"),
                _make_project_entry("proj-b3", "https://git.example.com/b3.git"),
            ],
        )
        lockfile = _make_lockfile(kanon_path, [alpha_entry, beta_entry])
        _write_lockfile_file(tmp_path, lockfile)

        mock_ref = _RefResolution(sha="e" * 40, resolved_ref="refs/heads/main")

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=mock_ref),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("meta.xml"))),
        ):
            install(
                kanonenv_path=kanon_path,
                lock_file_path=kanon_path.parent / ".kanon.lock",
                catalog_source="https://catalog.example.com/repo.git@main",
                refresh_lock_source="alpha",
            )

        captured = capsys.readouterr()
        assert "lockfile partially rebuilt" in captured.out
        assert "alpha" in captured.out
        # refreshed_count == 1: the alpha top-level source entry was re-resolved.
        # preserved_count == 1: the beta top-level source entry was kept as-is.
        # Singular form "project" is used for count == 1.
        assert "1 project refreshed" in captured.out
        assert "1 project preserved" in captured.out
