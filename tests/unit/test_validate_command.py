"""Tests for the validate command handler."""

import json
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kanon_cli.commands.validate import (
    _resolve_kanonenv_path,
    _resolve_repo_root,
    _run_marketplace,
    _run_xml,
    validate_lockfile_command,
    validate_metadata_command,
)
from kanon_cli.core.lockfile import Lockfile, SourceEntry, write_lockfile


_VALID_SHA40 = "a" * 40
_VALID_KANON_HASH = "sha256:" + "a" * 64
_LOCK_FILENAME = ".kanon.lock"
_KANONENV_FILENAME = ".kanon"


def _write_kanon(directory: Path, sources: dict[str, dict[str, str]]) -> Path:
    """Write a minimal .kanon file declaring the given source triples and return its path.

    Args:
        directory: Directory the .kanon file is written into.
        sources: Mapping of alias to a dict carrying ``url``, ``revision`` and
            ``path`` for that source.

    Returns:
        The path to the written .kanon file.
    """
    lines: list[str] = []
    for alias, data in sources.items():
        lines.append(f"KANON_SOURCE_{alias}_URL={data['url']}")
        lines.append(f"KANON_SOURCE_{alias}_REF={data['revision']}")
        lines.append(f"KANON_SOURCE_{alias}_PATH={data['path']}")
        lines.append(f"KANON_SOURCE_{alias}_NAME={alias}")
        lines.append(f"KANON_SOURCE_{alias}_GITBASE=https://example.com")
    path = directory / _KANONENV_FILENAME
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_lock(directory: Path, sources: list[SourceEntry]) -> Path:
    """Write a v4 lock file carrying the given source entries and return its path.

    Args:
        directory: Directory the .kanon.lock file is written into.
        sources: The list of alias-keyed SourceEntry objects to serialise.

    Returns:
        The path to the written .kanon.lock file.
    """
    lockfile = Lockfile(
        schema_version=4,
        generated_at="2026-01-01T00:00:00Z",
        generator="kanon-cli/3.0.0",
        kanon_hash=_VALID_KANON_HASH,
        sources=sources,
    )
    path = directory / _LOCK_FILENAME
    write_lockfile(lockfile, path)
    return path


def _source_entry(alias: str, ref_spec: str) -> SourceEntry:
    """Return a v4 SourceEntry for the given alias and ref-spec with valid scalar fields."""
    return SourceEntry(
        alias=alias,
        name=alias,
        url=f"https://example.com/{alias}.git",
        ref_spec=ref_spec,
        resolved_ref="refs/heads/main",
        resolved_sha=_VALID_SHA40,
        path=f"repo-specs/{alias}.xml",
    )


@pytest.mark.unit
class TestResolveRepoRoot:
    def test_explicit_path(self, tmp_path) -> None:
        """An existing absolute --repo-root directory is returned resolved."""
        result = _resolve_repo_root(tmp_path)
        assert result == tmp_path.resolve()
        assert result.is_absolute()

    def test_explicit_relative_path_is_resolved_to_abspath(self, tmp_path, monkeypatch) -> None:
        """A relative --repo-root is resolved to an absolute path at the CLI boundary.

        Downstream validators use ``xml_file.relative_to(repo_root)`` and
        ``repo_root / name`` for include resolution; both require consistent
        rooting. Resolving at the entry point guarantees that consistency
        regardless of whether the user passed ``--repo-root .`` or a full
        absolute path.
        """
        monkeypatch.chdir(tmp_path)
        result = _resolve_repo_root(Path("."))
        assert result.is_absolute(), f"--repo-root must be resolved to an absolute path, got {result!r}"
        assert result == tmp_path.resolve()

    def test_explicit_path_that_does_not_exist_fails_fast(self, tmp_path, capsys) -> None:
        """A non-existent --repo-root directory exits 1 with a clear message."""
        missing = tmp_path / "does-not-exist"
        with pytest.raises(SystemExit) as exc_info:
            _resolve_repo_root(missing)
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "--repo-root directory not found" in captured.err, (
            f"stderr must name the missing directory, got {captured.err!r}"
        )

    def test_auto_detect(self) -> None:
        with patch("kanon_cli.commands.validate.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="/detected/root\n", stderr="")
            result = _resolve_repo_root(None)
            assert result == Path("/detected/root")

    def test_auto_detect_fails(self) -> None:
        with patch("kanon_cli.commands.validate.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=128, stdout="", stderr="not a git repo")
            with pytest.raises(SystemExit):
                _resolve_repo_root(None)


@pytest.mark.unit
class TestRunXml:
    def test_dispatches_to_validate_xml(self, tmp_path: Path) -> None:
        args = types.SimpleNamespace(repo_root=tmp_path)
        with patch("kanon_cli.commands.validate.validate_xml", return_value=0):
            with pytest.raises(SystemExit) as exc_info:
                _run_xml(args)
            assert exc_info.value.code == 0


@pytest.mark.unit
class TestRunMarketplace:
    def test_dispatches_to_validate_marketplace(self, tmp_path: Path) -> None:
        args = types.SimpleNamespace(repo_root=tmp_path)
        with patch("kanon_cli.commands.validate.validate_marketplace", return_value=0):
            with pytest.raises(SystemExit) as exc_info:
                _run_marketplace(args)
            assert exc_info.value.code == 0


@pytest.mark.unit
class TestValidateMetadataCommandJsonOutput:
    """validate_metadata_command JSON output uses _build_findings_payload."""

    def test_json_format_calls_emit_json_payload(self, tmp_path: Path, capsys) -> None:
        """validate_metadata_command --format json routes output through _emit_json_payload."""
        repo_specs = tmp_path / "repo-specs"
        repo_specs.mkdir()
        (repo_specs / "alpha-marketplace.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            "<manifest><catalog-metadata>"
            "<name>alpha</name><display-name>Alpha</display-name>"
            "<description>Desc.</description><version>1.0.0</version>"
            "<type>plugin</type><owner-name>T</owner-name>"
            "<owner-email>t@e.com</owner-email><keywords>k</keywords>"
            "</catalog-metadata></manifest>"
        )
        args = types.SimpleNamespace(repo_root=tmp_path, format="json")

        with pytest.raises(SystemExit) as exc_info:
            validate_metadata_command(args)

        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert "findings" in parsed
        assert isinstance(parsed["findings"], list)


@pytest.mark.unit
class TestResolveKanonenvPath:
    """_resolve_kanonenv_path resolves an explicit path or auto-discovers .kanon."""

    def test_explicit_existing_path_is_resolved(self, tmp_path: Path) -> None:
        """An existing explicit .kanon path is returned resolved to an absolute path."""
        kanon_path = _write_kanon(tmp_path, {"alpha": {"url": "u", "revision": "main", "path": "p"}})
        result = _resolve_kanonenv_path(kanon_path)
        assert result == kanon_path.resolve()
        assert result.is_absolute()

    def test_explicit_missing_path_exits_1(self, tmp_path: Path, capsys) -> None:
        """A non-existent explicit .kanon path exits 1 naming the missing file."""
        missing = tmp_path / "does-not-exist.kanon"
        with pytest.raises(SystemExit) as exc_info:
            _resolve_kanonenv_path(missing)
        assert exc_info.value.code == 1
        assert ".kanon file not found" in capsys.readouterr().err

    def test_auto_discovery_failure_exits_1(self, capsys) -> None:
        """When auto-discovery raises FileNotFoundError the handler exits 1 with the message."""
        with patch(
            "kanon_cli.commands.validate.find_kanonenv",
            side_effect=FileNotFoundError("No .kanon file found anywhere"),
        ):
            with pytest.raises(SystemExit) as exc_info:
                _resolve_kanonenv_path(None)
        assert exc_info.value.code == 1
        assert "No .kanon file found anywhere" in capsys.readouterr().err


@pytest.mark.unit
class TestValidateLockfileCommand:
    """validate_lockfile_command flags .kanon <-> .kanon.lock drift and exits 0 on a consistent pair."""

    def test_consistent_pair_exits_0(self, tmp_path: Path, capsys) -> None:
        """A .kanon and lock with the same alias set and ref-specs exits 0."""
        kanon_path = _write_kanon(
            tmp_path,
            {
                "alpha": {"url": "https://example.com/alpha.git", "revision": "main", "path": "p1"},
                "beta": {"url": "https://example.com/beta.git", "revision": "==1.2.3", "path": "p2"},
            },
        )
        _write_lock(tmp_path, [_source_entry("alpha", "main"), _source_entry("beta", "==1.2.3")])
        args = types.SimpleNamespace(kanonenv_path=kanon_path, lock_file=None)

        with pytest.raises(SystemExit) as exc_info:
            validate_lockfile_command(args)
        assert exc_info.value.code == 0
        assert "are consistent" in capsys.readouterr().out

    def test_alias_set_drift_exits_1(self, tmp_path: Path, capsys) -> None:
        """A .kanon declaring an alias absent from the lock exits 1 naming the drift."""
        kanon_path = _write_kanon(
            tmp_path,
            {
                "alpha": {"url": "https://example.com/alpha.git", "revision": "main", "path": "p1"},
                "beta": {"url": "https://example.com/beta.git", "revision": "main", "path": "p2"},
            },
        )
        _write_lock(tmp_path, [_source_entry("alpha", "main")])
        args = types.SimpleNamespace(kanonenv_path=kanon_path, lock_file=None)

        with pytest.raises(SystemExit) as exc_info:
            validate_lockfile_command(args)
        assert exc_info.value.code == 1
        assert "alias sets differ" in capsys.readouterr().err

    def test_ref_spec_drift_exits_1(self, tmp_path: Path, capsys) -> None:
        """A per-alias ref-spec that differs between .kanon and the lock exits 1."""
        kanon_path = _write_kanon(
            tmp_path,
            {"alpha": {"url": "https://example.com/alpha.git", "revision": "==2.0.0", "path": "p1"}},
        )
        _write_lock(tmp_path, [_source_entry("alpha", "main")])
        args = types.SimpleNamespace(kanonenv_path=kanon_path, lock_file=None)

        with pytest.raises(SystemExit) as exc_info:
            validate_lockfile_command(args)
        assert exc_info.value.code == 1
        assert "ref-specs differ" in capsys.readouterr().err

    def test_duplicate_alias_in_kanon_exits_1(self, tmp_path: Path, capsys) -> None:
        """A duplicate KANON_SOURCE_<alias>_* key in .kanon exits 1 (duplicate-alias error)."""
        kanon_path = tmp_path / _KANONENV_FILENAME
        kanon_path.write_text(
            "KANON_SOURCE_alpha_URL=https://example.com/alpha.git\n"
            "KANON_SOURCE_alpha_REF=main\n"
            "KANON_SOURCE_alpha_PATH=p1\n"
            "KANON_SOURCE_alpha_URL=https://example.com/dup.git\n",
            encoding="utf-8",
        )
        _write_lock(tmp_path, [_source_entry("alpha", "main")])
        args = types.SimpleNamespace(kanonenv_path=kanon_path, lock_file=None)

        with pytest.raises(SystemExit) as exc_info:
            validate_lockfile_command(args)
        assert exc_info.value.code == 1
        assert "Duplicate key" in capsys.readouterr().err

    def test_missing_lockfile_exits_1(self, tmp_path: Path, capsys) -> None:
        """A .kanon with no corresponding .kanon.lock exits 1 naming the missing lock."""
        kanon_path = _write_kanon(
            tmp_path,
            {"alpha": {"url": "https://example.com/alpha.git", "revision": "main", "path": "p1"}},
        )
        args = types.SimpleNamespace(kanonenv_path=kanon_path, lock_file=None)

        with pytest.raises(SystemExit) as exc_info:
            validate_lockfile_command(args)
        assert exc_info.value.code == 1
        assert ".kanon.lock file not found" in capsys.readouterr().err

    def test_explicit_lock_file_override_is_used(self, tmp_path: Path, capsys) -> None:
        """The --lock-file override path is read instead of the derived <kanon>.lock path."""
        kanon_path = _write_kanon(
            tmp_path,
            {"alpha": {"url": "https://example.com/alpha.git", "revision": "main", "path": "p1"}},
        )
        alt_dir = tmp_path / "alt"
        alt_dir.mkdir()
        alt_lock = _write_lock(alt_dir, [_source_entry("alpha", "main")])
        args = types.SimpleNamespace(kanonenv_path=kanon_path, lock_file=alt_lock)

        with pytest.raises(SystemExit) as exc_info:
            validate_lockfile_command(args)
        assert exc_info.value.code == 0
        out = capsys.readouterr().out
        assert str(alt_lock) in out
