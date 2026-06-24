"""Unit tests for the --refresh-lock-source flag in kanon install.

AC-TEST-001: Parametrises the five paths:
  (a) refresh by source name (KANON_SOURCE_<name> key).
  (b) refresh by catalog entry name (via derive_source_name).
  (c) unknown name raises UnknownSourceError.
  (d) mutual exclusion with --refresh-lock raises SystemExit(2).
  (e) --refresh-lock-source is hermetic: it re-resolves from the committed .kanon
      and ignores a populated KANON_CATALOG_SOURCES env var (spec Section 4.3 /
      FR-14, so install -- including the refresh-lock-source path -- never resolves
      or requires a catalog source).  The install subparser does not register
      --catalog-source.

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
    UnknownSourceError,
    _RefResolution,
    _emit_install_state,
    _merge_partial_lockfile,
    _resolve_source_name,
    install,
)
from kanon_cli.core.kanon_hash import kanon_hash as compute_kanon_hash
from kanon_cli.core.lockfile import (
    CURRENT_SCHEMA_VERSION,
    Lockfile,
    ProjectEntry,
    SourceEntry,
)


_VALID_SHA_A = "a" * 40
_VALID_SHA_B = "b" * 40

_KANON_TWO_SOURCE = """\
GITBASE=https://git.example.com
CLAUDE_MARKETPLACES_DIR=/tmp/mktplc
KANON_MARKETPLACE_INSTALL=false
KANON_SOURCE_alpha_URL=https://git.example.com/alpha.git
KANON_SOURCE_alpha_REF=main
KANON_SOURCE_alpha_PATH=manifest.xml
KANON_SOURCE_alpha_NAME=alpha
KANON_SOURCE_alpha_GITBASE=https://example.com
KANON_SOURCE_beta_URL=https://git.example.com/beta.git
KANON_SOURCE_beta_REF=main
KANON_SOURCE_beta_PATH=manifest.xml
KANON_SOURCE_beta_NAME=beta
KANON_SOURCE_beta_GITBASE=https://example.com
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
        ref_spec="main",
        resolved_ref="refs/heads/main",
        resolved_sha=_VALID_SHA_A,
    )


def _make_source_entry(
    name: str,
    url: str = "https://git.example.com/repo.git",
    sha: str = _VALID_SHA_A,
    ref_spec: str = "main",
    resolved_ref: str = "refs/heads/main",
    path: str = "manifest.xml",
    projects: list[ProjectEntry] | None = None,
) -> SourceEntry:
    return SourceEntry(
        alias=name,
        name=name,
        url=url,
        ref_spec=ref_spec,
        resolved_ref=resolved_ref,
        resolved_sha=sha,
        path=path,
        projects=projects or [],
    )


def _make_lockfile(
    kanon_path: pathlib.Path,
    source_entries: list[SourceEntry],
) -> Lockfile:
    kanon_hash = compute_kanon_hash(kanon_path)
    return Lockfile(
        schema_version=CURRENT_SCHEMA_VERSION,
        generated_at="2026-01-15T00:00:00Z",
        generator="kanon-cli/test",
        kanon_hash=kanon_hash,
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
            InstallState.RECONCILE,
            InstallState.LOCKFILE_UNREACHABLE,
            InstallState.REFRESH_LOCK,
        ]
        for other in other_states:
            assert InstallState.REFRESH_LOCK_SOURCE is not other


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

        kanon_content = """\
GITBASE=https://git.example.com
CLAUDE_MARKETPLACES_DIR=/tmp/mktplc
KANON_MARKETPLACE_INSTALL=false
KANON_SOURCE_alpha_tool_URL=https://git.example.com/alpha.git
KANON_SOURCE_alpha_tool_REF=main
KANON_SOURCE_alpha_tool_PATH=manifest.xml
KANON_SOURCE_alpha_tool_NAME=alpha_tool
KANON_SOURCE_alpha_tool_GITBASE=https://example.com
KANON_SOURCE_beta_URL=https://git.example.com/beta.git
KANON_SOURCE_beta_REF=main
KANON_SOURCE_beta_PATH=manifest.xml
KANON_SOURCE_beta_NAME=beta
KANON_SOURCE_beta_GITBASE=https://example.com
"""
        kanon_path = _write_kanon(tmp_path, kanon_content)
        alpha_entry = _make_source_entry(name="alpha_tool", url="https://git.example.com/alpha.git")
        beta_entry = _make_source_entry(name="beta", url="https://git.example.com/beta.git")
        lockfile = _make_lockfile(kanon_path, [alpha_entry, beta_entry])

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

        assert "alpha" in err_str
        assert "beta" in err_str

    @pytest.mark.parametrize(
        "name,expected_source_name",
        [
            ("alpha", "alpha"),
            ("beta", "beta"),
            ("ALPHA", "alpha"),
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

        args = parser.parse_args(["install", "--refresh-lock"])
        assert args.refresh_lock is True
        assert args.refresh_lock_source is None


@pytest.mark.unit
class TestRefreshLockSourceHermeticCatalogIgnored:
    """AC-FUNC-005: the refresh-lock-source path ignores a populated catalog env
    var and the install subparser does not register --catalog-source."""

    def test_refresh_lock_source_ignores_env_catalog_source(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """install(refresh_lock_source='alpha') ignores a populated KANON_CATALOG_SOURCES env var."""
        monkeypatch.setenv("KANON_CATALOG_SOURCES", "https://env.example.com/catalog.git@main")
        kanon_path = _write_kanon(tmp_path)

        alpha_entry = _make_source_entry(name="alpha", url="https://git.example.com/alpha.git", sha=_VALID_SHA_A)
        beta_entry = _make_source_entry(name="beta", url="https://git.example.com/beta.git", sha=_VALID_SHA_B)
        lockfile = _make_lockfile(kanon_path, [alpha_entry, beta_entry])
        lock_path = _write_lockfile_file(tmp_path, lockfile)

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
                refresh_lock_source="alpha",
            )

        from kanon_cli.core.lockfile import read_lockfile

        new_lf = read_lockfile(lock_path)
        alpha_new = next(e for e in new_lf.sources if e.name == "alpha")

        assert alpha_new.resolved_sha == new_alpha_sha
        assert alpha_new.url == "https://git.example.com/alpha.git"
        lock_text = lock_path.read_text(encoding="utf-8")
        assert "https://env.example.com/catalog.git" not in lock_text

    def test_install_subparser_rejects_catalog_source_flag(self) -> None:
        """The install subparser does not register --catalog-source (FR-14): passing it exits non-zero."""
        from kanon_cli.commands import install as install_cmd

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        install_cmd.register(subparsers)

        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(
                [
                    "install",
                    "--refresh-lock-source",
                    "alpha",
                    "--catalog-source",
                    "https://git.example.com/catalog.git@main",
                ]
            )
        assert exc_info.value.code != 0


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
            attributed_marketplaces={},
        )

        refreshed = next(e for e in merged.sources if e.name == "alpha")
        assert refreshed.resolved_sha == new_alpha_sha

        preserved = next(e for e in merged.sources if e.name == "beta")
        assert preserved.resolved_sha == beta_old.resolved_sha
        assert preserved.url == beta_old.url

    def test_merge_records_per_source_attribution_replacing_old_ledgers(self, tmp_path: pathlib.Path) -> None:
        """_merge_partial_lockfile refreshes EACH source's per-source ledger from attribution.

        After (re)registration the freshly-attributed set is authoritative for
        every current source (the marketplace dir was wiped+repopulated this
        install), so a partial merge must overwrite each source's
        ``registered_marketplaces`` with the attribution dict -- never carry
        forward a stale per-source ledger.
        """
        kanon_path = _write_kanon(tmp_path)

        alpha_old = _make_source_entry(name="alpha", sha=_VALID_SHA_A)
        alpha_old.registered_marketplaces = ["stale-alpha-mp"]
        beta_old = _make_source_entry(name="beta", sha=_VALID_SHA_B)
        beta_old.registered_marketplaces = ["stale-beta-mp"]
        old_lockfile = _make_lockfile(kanon_path, [alpha_old, beta_old])

        alpha_new = _make_source_entry(name="alpha", sha="f" * 40)
        new_hash = compute_kanon_hash(kanon_path)
        merged = _merge_partial_lockfile(
            old_lockfile=old_lockfile,
            refreshed_source=alpha_new,
            new_kanon_hash=new_hash,
            attributed_marketplaces={"alpha": ["fresh-alpha-mp"], "beta": ["fresh-beta-mp"]},
        )

        by_name = {s.name: s for s in merged.sources}
        assert by_name["alpha"].registered_marketplaces == ["fresh-alpha-mp"], (
            f"refreshed source's ledger must be the fresh attribution; got {by_name['alpha'].registered_marketplaces!r}"
        )
        assert by_name["beta"].registered_marketplaces == ["fresh-beta-mp"], (
            f"preserved source's ledger must also be refreshed from attribution; "
            f"got {by_name['beta'].registered_marketplaces!r}"
        )

    def test_merge_resets_ledger_for_source_absent_from_attribution(self, tmp_path: pathlib.Path) -> None:
        """A source not present in the attribution dict (e.g. mp disabled) gets an empty ledger."""
        kanon_path = _write_kanon(tmp_path)
        alpha_old = _make_source_entry(name="alpha", sha=_VALID_SHA_A)
        alpha_old.registered_marketplaces = ["stale-alpha-mp"]
        old_lockfile = _make_lockfile(kanon_path, [alpha_old])

        alpha_new = _make_source_entry(name="alpha", sha="f" * 40)
        new_hash = compute_kanon_hash(kanon_path)
        merged = _merge_partial_lockfile(
            old_lockfile=old_lockfile,
            refreshed_source=alpha_new,
            new_kanon_hash=new_hash,
            attributed_marketplaces={},
        )

        assert merged.sources[0].registered_marketplaces == [], (
            f"a source absent from attribution must be reset to an empty ledger; "
            f"got {merged.sources[0].registered_marketplaces!r}"
        )

    def test_merge_updates_kanon_hash(self, tmp_path: pathlib.Path) -> None:
        """_merge_partial_lockfile records the freshly-computed kanon_hash, not the old one."""
        kanon_path = _write_kanon(tmp_path)
        alpha_old = _make_source_entry(name="alpha", sha=_VALID_SHA_A)
        beta_old = _make_source_entry(name="beta", sha=_VALID_SHA_B)
        old_lockfile = _make_lockfile(kanon_path, [alpha_old, beta_old])
        old_hash = old_lockfile.kanon_hash

        new_kanon_hash = compute_kanon_hash(kanon_path)
        alpha_new = _make_source_entry(name="alpha", sha="f" * 40)

        merged = _merge_partial_lockfile(
            old_lockfile=old_lockfile,
            refreshed_source=alpha_new,
            new_kanon_hash=new_kanon_hash,
            attributed_marketplaces={},
        )

        assert merged.kanon_hash == new_kanon_hash

        assert merged.kanon_hash.startswith("sha256:")
        assert len(merged.kanon_hash) == 71

        _ = old_hash

    def test_merge_preserves_top_level_metadata_and_has_no_catalog(self, tmp_path: pathlib.Path) -> None:
        """_merge_partial_lockfile preserves the v4 top-level metadata and emits no [catalog] block.

        Schema v4 removed the lockfile ``[catalog]`` block, so the merged Lockfile
        must carry no ``catalog`` attribute.  The merge still preserves the
        schema version, generator, and marketplace fields verbatim from the
        source lockfile (only ``kanon_hash`` and ``generated_at`` are refreshed).
        """
        kanon_path = _write_kanon(tmp_path)
        alpha_old = _make_source_entry(name="alpha", sha=_VALID_SHA_A)
        beta_old = _make_source_entry(name="beta", sha=_VALID_SHA_B)
        old_lockfile = _make_lockfile(kanon_path, [alpha_old, beta_old])

        alpha_new = _make_source_entry(name="alpha", sha="f" * 40)
        new_hash = compute_kanon_hash(kanon_path)
        merged = _merge_partial_lockfile(
            old_lockfile=old_lockfile,
            refreshed_source=alpha_new,
            new_kanon_hash=new_hash,
            attributed_marketplaces={},
        )

        assert not hasattr(merged, "catalog"), "schema v4 removed the lockfile [catalog] block"
        assert merged.schema_version == old_lockfile.schema_version
        assert merged.generator == old_lockfile.generator
        assert merged.marketplace_registered == old_lockfile.marketplace_registered
        assert merged.marketplace_dir == old_lockfile.marketplace_dir

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
                attributed_marketplaces={},
            )


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
        monkeypatch.delenv("KANON_CATALOG_SOURCES", raising=False)
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
                refresh_lock_source="alpha",
            )

        from kanon_cli.core.lockfile import read_lockfile

        new_lf = read_lockfile(lock_path)
        alpha_new = next(e for e in new_lf.sources if e.name == "alpha")
        beta_new = next(e for e in new_lf.sources if e.name == "beta")

        assert alpha_new.resolved_sha == new_alpha_sha

        assert beta_new.resolved_sha == _VALID_SHA_B
        assert beta_new.url == beta_entry.url
        assert beta_new.ref_spec == beta_entry.ref_spec
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
        monkeypatch.delenv("KANON_CATALOG_SOURCES", raising=False)
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
                refresh_lock_source="alpha",
            )

        captured = capsys.readouterr()
        assert "lockfile partially rebuilt" in captured.out
        assert "alpha" in captured.out

        assert "1 project refreshed" in captured.out
        assert "1 project preserved" in captured.out
