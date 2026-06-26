"""Unit tests for branch-pinned and SHA-pinned revision shapes in 'kanon outdated'.

Covers:
- Branch-pinned source with no drift (locked SHA == branch HEAD).
- Branch-pinned source with drift (locked SHA != branch HEAD).
- Branch-pinned source with no lockfile (current is live-resolved HEAD).
- SHA-pinned source (all three columns show same truncated SHA, upgrade-type=none).
- Revision shape classification across branch / tag / SHA / PEP 440-spec inputs.
- _resolve_lock_sha helper: None on absent file, None on missing entry, SHA on hit.
- run() dispatch: branch-pinned and SHA-pinned sources via patched _list_branch_head.
- _list_branch_head error paths: non-zero exit raises RuntimeError; branch not found
  raises ValueError; run() converts these to sys.exit(1).

AC-TEST-001
"""

import argparse
import pathlib
from unittest.mock import patch, MagicMock

import pytest

from kanon_cli.commands.outdated import _build_row
from kanon_cli.version import _classify_revision_shape, RevisionShape, _list_branch_head


@pytest.mark.unit
@pytest.mark.parametrize(
    "revision, expected_shape",
    [
        ("main", RevisionShape.BRANCH),
        ("develop", RevisionShape.BRANCH),
        ("feature/foo", RevisionShape.BRANCH),
        ("release/v1", RevisionShape.BRANCH),
        ("a" * 40, RevisionShape.SHA),
        ("b" * 64, RevisionShape.SHA),
        (">=1.0.0", RevisionShape.TAG),
        ("~=1.0.0", RevisionShape.TAG),
        (">=1.0.0,<2.0.0", RevisionShape.TAG),
        ("*", RevisionShape.TAG),
        ("latest", RevisionShape.TAG),
        ("refs/tags/>=1.0.0", RevisionShape.TAG),
        ("refs/tags/1.0.0", RevisionShape.TAG),
        ("refs/tags/~=1.0.0", RevisionShape.TAG),
    ],
)
class TestClassifyRevisionShape:
    def test_shape(self, revision: str, expected_shape: RevisionShape) -> None:
        result = _classify_revision_shape(revision)
        assert result == expected_shape, (
            f"_classify_revision_shape({revision!r}) returned {result!r}, expected {expected_shape!r}"
        )


_FAKE_HEAD_SHA_FULL = "abcdef1234567890abcdef1234567890abcdef12"
_FAKE_HEAD_SHA_12 = "abcdef123456"
_FAKE_OLD_SHA_FULL = "0011223344556677889900112233445566778899"
_FAKE_OLD_SHA_12 = "001122334455"


@pytest.mark.unit
class TestBranchPinnedNoDrift:
    """Branch-pinned source: locked SHA equals branch HEAD -> upgrade-type=none."""

    def test_no_drift_upgrade_type(self) -> None:
        source = {
            "url": "file:///some/repo",
            "ref": "main",
            "path": "./src",
        }
        with patch(
            "kanon_cli.commands.outdated._list_branch_head",
            return_value=_FAKE_HEAD_SHA_FULL,
        ):
            row = _build_row(
                name="FOO",
                source=source,
                available_tags=[],
                lock_ref=_FAKE_HEAD_SHA_FULL,
            )

        assert row.upgrade_type == "none", (
            f"Expected upgrade-type=none when locked SHA == HEAD, got {row.upgrade_type!r}"
        )

    def test_no_drift_latest_columns_show_truncated_head(self) -> None:
        source = {
            "url": "file:///some/repo",
            "ref": "main",
            "path": "./src",
        }
        with patch(
            "kanon_cli.commands.outdated._list_branch_head",
            return_value=_FAKE_HEAD_SHA_FULL,
        ):
            row = _build_row(
                name="FOO",
                source=source,
                available_tags=[],
                lock_ref=_FAKE_HEAD_SHA_FULL,
            )

        assert row.latest_matching_spec == _FAKE_HEAD_SHA_12, (
            f"latest-matching-spec should be 12-char truncated HEAD, got {row.latest_matching_spec!r}"
        )
        assert row.latest_available == _FAKE_HEAD_SHA_12, (
            f"latest-available should equal latest-matching-spec for branch-pinned, got {row.latest_available!r}"
        )

    def test_no_drift_current_column(self) -> None:
        source = {
            "url": "file:///some/repo",
            "ref": "main",
            "path": "./src",
        }
        with patch(
            "kanon_cli.commands.outdated._list_branch_head",
            return_value=_FAKE_HEAD_SHA_FULL,
        ):
            row = _build_row(
                name="FOO",
                source=source,
                available_tags=[],
                lock_ref=_FAKE_HEAD_SHA_FULL,
            )

        assert row.current == _FAKE_HEAD_SHA_12


@pytest.mark.unit
class TestBranchPinnedDrift:
    """Branch-pinned source: locked SHA differs from HEAD -> upgrade-type=drift."""

    def test_drift_upgrade_type(self) -> None:
        source = {
            "url": "file:///some/repo",
            "ref": "main",
            "path": "./src",
        }
        with patch(
            "kanon_cli.commands.outdated._list_branch_head",
            return_value=_FAKE_HEAD_SHA_FULL,
        ):
            row = _build_row(
                name="FOO",
                source=source,
                available_tags=[],
                lock_ref=_FAKE_OLD_SHA_FULL,
            )

        assert row.upgrade_type == "drift", (
            f"Expected upgrade-type=drift when locked SHA != HEAD, got {row.upgrade_type!r}"
        )

    def test_drift_current_shows_locked_truncated_sha(self) -> None:
        source = {
            "url": "file:///some/repo",
            "ref": "main",
            "path": "./src",
        }
        with patch(
            "kanon_cli.commands.outdated._list_branch_head",
            return_value=_FAKE_HEAD_SHA_FULL,
        ):
            row = _build_row(
                name="FOO",
                source=source,
                available_tags=[],
                lock_ref=_FAKE_OLD_SHA_FULL,
            )

        assert row.current == _FAKE_OLD_SHA_12, f"current column should show truncated locked SHA, got {row.current!r}"

    def test_drift_latest_columns_show_head_truncated(self) -> None:
        source = {
            "url": "file:///some/repo",
            "ref": "main",
            "path": "./src",
        }
        with patch(
            "kanon_cli.commands.outdated._list_branch_head",
            return_value=_FAKE_HEAD_SHA_FULL,
        ):
            row = _build_row(
                name="FOO",
                source=source,
                available_tags=[],
                lock_ref=_FAKE_OLD_SHA_FULL,
            )

        assert row.latest_matching_spec == _FAKE_HEAD_SHA_12
        assert row.latest_available == _FAKE_HEAD_SHA_12


@pytest.mark.unit
@pytest.mark.parametrize(
    "branch_name",
    ["main", "develop", "feature/foo", "release/v1"],
)
class TestBranchPinnedDriftBranchNames:
    """Parametrized: various branch shapes all produce drift when locked != HEAD."""

    def test_branch_drift_parametrized(self, branch_name: str) -> None:
        source = {
            "url": "file:///some/repo",
            "ref": branch_name,
            "path": "./src",
        }
        with patch(
            "kanon_cli.commands.outdated._list_branch_head",
            return_value=_FAKE_HEAD_SHA_FULL,
        ):
            row = _build_row(
                name="SRC",
                source=source,
                available_tags=[],
                lock_ref=_FAKE_OLD_SHA_FULL,
            )

        assert row.upgrade_type == "drift"
        assert row.latest_matching_spec == _FAKE_HEAD_SHA_12
        assert row.latest_available == _FAKE_HEAD_SHA_12


@pytest.mark.unit
class TestBranchPinnedNoLockfile:
    """Branch-pinned source with no lockfile: current is live-resolved HEAD."""

    def test_no_lockfile_current_equals_head_truncated(self) -> None:
        source = {
            "url": "file:///some/repo",
            "ref": "main",
            "path": "./src",
        }
        with patch(
            "kanon_cli.commands.outdated._list_branch_head",
            return_value=_FAKE_HEAD_SHA_FULL,
        ):
            row = _build_row(
                name="FOO",
                source=source,
                available_tags=[],
                lock_ref=None,
            )

        assert row.current == _FAKE_HEAD_SHA_12, (
            f"Without lockfile, current should be live-resolved HEAD (12-char), got {row.current!r}"
        )

    def test_no_lockfile_upgrade_type_none(self) -> None:
        """Without lockfile, current == head, so upgrade-type=none."""
        source = {
            "url": "file:///some/repo",
            "ref": "main",
            "path": "./src",
        }
        with patch(
            "kanon_cli.commands.outdated._list_branch_head",
            return_value=_FAKE_HEAD_SHA_FULL,
        ):
            row = _build_row(
                name="FOO",
                source=source,
                available_tags=[],
                lock_ref=None,
            )

        assert row.upgrade_type == "none"

    def test_no_lockfile_latest_columns_show_head(self) -> None:
        source = {
            "url": "file:///some/repo",
            "ref": "main",
            "path": "./src",
        }
        with patch(
            "kanon_cli.commands.outdated._list_branch_head",
            return_value=_FAKE_HEAD_SHA_FULL,
        ):
            row = _build_row(
                name="FOO",
                source=source,
                available_tags=[],
                lock_ref=None,
            )

        assert row.latest_matching_spec == _FAKE_HEAD_SHA_12
        assert row.latest_available == _FAKE_HEAD_SHA_12


@pytest.mark.unit
class TestShaPinned:
    """SHA-pinned source: all three columns show same truncated SHA, upgrade-type=none."""

    def test_sha_pinned_40_char(self) -> None:
        sha_40 = "a" * 40
        sha_12 = "a" * 12
        source = {
            "url": "file:///some/repo",
            "ref": sha_40,
            "path": "./src",
        }
        row = _build_row(
            name="FOO",
            source=source,
            available_tags=[],
            lock_ref=sha_40,
        )

        assert row.current == sha_12
        assert row.latest_matching_spec == sha_12
        assert row.latest_available == sha_12
        assert row.upgrade_type == "none"

    def test_sha_pinned_64_char(self) -> None:
        sha_64 = "b" * 64
        sha_12 = "b" * 12
        source = {
            "url": "file:///some/repo",
            "ref": sha_64,
            "path": "./src",
        }
        row = _build_row(
            name="FOO",
            source=source,
            available_tags=[],
            lock_ref=sha_64,
        )

        assert row.current == sha_12
        assert row.latest_matching_spec == sha_12
        assert row.latest_available == sha_12
        assert row.upgrade_type == "none"

    def test_sha_pinned_no_lockfile(self) -> None:
        """SHA-pinned with no lockfile: current, latest-* are all the truncated revision SHA."""
        sha_40 = "c" * 40
        sha_12 = "c" * 12
        source = {
            "url": "file:///some/repo",
            "ref": sha_40,
            "path": "./src",
        }
        row = _build_row(
            name="FOO",
            source=source,
            available_tags=[],
            lock_ref=None,
        )

        assert row.current == sha_12
        assert row.latest_matching_spec == sha_12
        assert row.latest_available == sha_12
        assert row.upgrade_type == "none"

    def test_sha_pinned_upgrade_type_always_none(self) -> None:
        """SHA-pinned upgrade-type is always none regardless of lock_ref content."""
        sha_40 = "d" * 40
        sha_12 = "d" * 12
        source = {
            "url": "file:///some/repo",
            "ref": sha_40,
            "path": "./src",
        }

        row = _build_row(
            name="FOO",
            source=source,
            available_tags=[],
            lock_ref=sha_40,
        )

        assert row.upgrade_type == "none"
        assert row.latest_matching_spec == sha_12
        assert row.latest_available == sha_12


@pytest.mark.unit
@pytest.mark.parametrize(
    "full_sha, expected_12",
    [
        ("abcdef1234567890" + "0" * 24, "abcdef123456"),
        ("1234567890abcdef" + "0" * 24, "1234567890ab"),
        ("f" * 40, "f" * 12),
        ("0" * 64, "0" * 12),
    ],
)
class TestShaTruncation:
    def test_truncation_length(self, full_sha: str, expected_12: str) -> None:
        """Branch HEAD SHA is truncated to exactly 12 leading hex chars."""
        source = {
            "url": "file:///some/repo",
            "ref": "main",
            "path": "./src",
        }
        with patch(
            "kanon_cli.commands.outdated._list_branch_head",
            return_value=full_sha,
        ):
            row = _build_row(
                name="FOO",
                source=source,
                available_tags=[],
                lock_ref=None,
            )

        assert row.latest_matching_spec == expected_12
        assert len(row.latest_matching_spec) == 12


@pytest.mark.unit
class TestResolveLockSha:
    """Tests for _resolve_lock_sha helper in outdated.py."""

    def test_returns_none_when_path_is_none(self) -> None:
        """_resolve_lock_sha returns None when lock_file_path is None."""
        from kanon_cli.commands.outdated import _resolve_lock_sha

        result = _resolve_lock_sha("FOO", None)
        assert result is None

    def test_returns_none_when_file_does_not_exist(self, tmp_path: pathlib.Path) -> None:
        """_resolve_lock_sha returns None when lockfile does not exist."""
        from kanon_cli.commands.outdated import _resolve_lock_sha

        missing = tmp_path / "nonexistent.lock"
        result = _resolve_lock_sha("FOO", missing)
        assert result is None

    def test_returns_sha_when_source_present(self, tmp_path: pathlib.Path) -> None:
        """_resolve_lock_sha returns resolved_sha when source entry is found."""
        from kanon_cli.commands.outdated import _resolve_lock_sha

        sha = "a" * 40
        lock_file = tmp_path / ".kanon.lock"
        lock_file.write_text(
            "schema_version = 5\n"
            'generated_at = "2026-01-01T00:00:00Z"\n'
            'generator = "kanon-cli/test"\n'
            f'kanon_hash = "sha256:{"a" * 64}"\n'
            "\n"
            "[[sources]]\n"
            'alias = "FOO"\n'
            'name = "FOO"\n'
            'url = "file:///some/repo"\n'
            'ref_spec = "main"\n'
            'resolved_ref = "refs/heads/main"\n'
            f'resolved_sha = "{sha}"\n'
            'path = "./foo"\n'
        )
        result = _resolve_lock_sha("FOO", lock_file)
        assert result == sha

    def test_returns_none_when_source_not_in_lockfile(self, tmp_path: pathlib.Path) -> None:
        """_resolve_lock_sha returns None when source name is not in lockfile."""
        from kanon_cli.commands.outdated import _resolve_lock_sha

        sha = "b" * 40
        lock_file = tmp_path / ".kanon.lock"
        lock_file.write_text(
            "schema_version = 5\n"
            'generated_at = "2026-01-01T00:00:00Z"\n'
            'generator = "kanon-cli/test"\n'
            f'kanon_hash = "sha256:{"a" * 64}"\n'
            "\n"
            "[[sources]]\n"
            'alias = "BAR"\n'
            'name = "BAR"\n'
            'url = "file:///some/repo"\n'
            'ref_spec = "main"\n'
            'resolved_ref = "refs/heads/main"\n'
            f'resolved_sha = "{sha}"\n'
            'path = "./bar"\n'
        )
        result = _resolve_lock_sha("FOO", lock_file)
        assert result is None


def _make_args(
    catalog_source: str | None = "file:///fake/catalog@HEAD",
    kanon_file: str = "/fake/.kanon",
    lock_file: str | None = None,
    format: str = "table",
    fail_on_upgrade: bool = False,
) -> argparse.Namespace:
    """Build a minimal argparse Namespace for the outdated subcommand."""
    return argparse.Namespace(
        catalog_source=catalog_source,
        kanon_file=kanon_file,
        lock_file=lock_file,
        format=format,
        fail_on_upgrade=fail_on_upgrade,
    )


@pytest.mark.unit
class TestRunDispatchBranchPinned:
    """run() correctly dispatches branch-pinned sources without calling _list_tags."""

    def test_run_branch_pinned_uses_branch_head(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """run() uses _list_branch_head for branch-pinned sources, not _list_tags."""
        from kanon_cli.commands.outdated import run

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "GITBASE=file:///unused\n"
            "CLAUDE_MARKETPLACES_DIR=/tmp/.claude\n"
            "KANON_MARKETPLACE_INSTALL=false\n"
            "KANON_SOURCE_FOO_URL=file:///some/repo\n"
            "KANON_SOURCE_FOO_REF=main\n"
            "KANON_SOURCE_FOO_PATH=./foo\n"
            "KANON_SOURCE_FOO_NAME=FOO\n"
            "KANON_SOURCE_FOO_GITBASE=https://example.com\n"
        )
        kanon_file.chmod(0o644)

        head_sha = "abcdef1234567890abcdef1234567890abcdef12"
        head_sha_12 = head_sha[:12]

        args = _make_args(
            catalog_source="file:///fake/catalog@HEAD",
            kanon_file=str(kanon_file),
        )

        with (
            patch(
                "kanon_cli.commands.outdated._list_branch_head",
                return_value=head_sha,
            ) as mock_branch_head,
            patch("kanon_cli.commands.outdated._list_tags") as mock_list_tags,
        ):
            result = run(args)

        assert result == 0
        mock_branch_head.assert_called_once_with("file:///some/repo", "main")
        mock_list_tags.assert_not_called()
        captured = capsys.readouterr()
        assert head_sha_12 in captured.out
        assert "none" in captured.out


@pytest.mark.unit
class TestRunDispatchShaPinned:
    """run() correctly dispatches SHA-pinned sources without network calls."""

    def test_run_sha_pinned_no_network_calls(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """run() makes no git calls for SHA-pinned sources."""
        from kanon_cli.commands.outdated import run

        sha_40 = "a" * 40
        sha_12 = "a" * 12

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "GITBASE=file:///unused\n"
            "CLAUDE_MARKETPLACES_DIR=/tmp/.claude\n"
            "KANON_MARKETPLACE_INSTALL=false\n"
            f"KANON_SOURCE_FOO_URL=file:///some/repo\n"
            f"KANON_SOURCE_FOO_REF={sha_40}\n"
            "KANON_SOURCE_FOO_PATH=./foo\n"
            "KANON_SOURCE_FOO_NAME=FOO\n"
            "KANON_SOURCE_FOO_GITBASE=https://example.com\n"
        )
        kanon_file.chmod(0o644)

        args = _make_args(
            catalog_source="file:///fake/catalog@HEAD",
            kanon_file=str(kanon_file),
        )

        with (
            patch("kanon_cli.commands.outdated._list_tags") as mock_list_tags,
            patch("kanon_cli.commands.outdated._list_branch_head") as mock_branch_head,
        ):
            result = run(args)

        assert result == 0
        mock_list_tags.assert_not_called()
        mock_branch_head.assert_not_called()
        captured = capsys.readouterr()
        assert sha_12 in captured.out
        assert "none" in captured.out


@pytest.mark.unit
class TestListBranchHeadErrors:
    """Error path tests for _list_branch_head in version.py.

    _list_branch_head is library code: it raises RuntimeError on git failures
    and ValueError when the branch is not found. The CLI command handler
    (outdated.run) is responsible for catching these and calling sys.exit(1).
    """

    def test_nonzero_exit_code_raises_runtime_error(self) -> None:
        """Non-zero git ls-remote exit code raises RuntimeError."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "fatal: repository not found"

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="ERROR:"):
                _list_branch_head("file:///nonexistent", "main")

    def test_nonzero_exit_code_error_message_contains_url(self) -> None:
        """RuntimeError message from non-zero exit includes the URL."""
        mock_result = MagicMock()
        mock_result.returncode = 2
        mock_result.stderr = "transport error"

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError) as exc_info:
                _list_branch_head("file:///some/repo", "main")

        assert "file:///some/repo" in str(exc_info.value)

    def test_branch_not_found_raises_value_error(self) -> None:
        """Empty git ls-remote output (branch not found) raises ValueError."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(ValueError, match="not found on remote"):
                _list_branch_head("file:///some/repo", "nonexistent-branch")

    def test_branch_not_found_error_includes_branch_name(self) -> None:
        """ValueError for missing branch includes the branch name."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "abc123\trefs/heads/other-branch\n"

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(ValueError) as exc_info:
                _list_branch_head("file:///some/repo", "my-branch")

        assert "my-branch" in str(exc_info.value) or "refs/heads/" in str(exc_info.value)

    def test_git_not_found_raises_runtime_error(self) -> None:
        """FileNotFoundError when git binary is missing raises RuntimeError."""
        with patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
            with pytest.raises(RuntimeError, match="ERROR:"):
                _list_branch_head("file:///some/repo", "main")

    def test_git_not_found_error_message_mentions_git(self) -> None:
        """RuntimeError message when git binary is absent mentions 'git'."""
        with patch("subprocess.run", side_effect=FileNotFoundError("git not found")):
            with pytest.raises(RuntimeError) as exc_info:
                _list_branch_head("file:///some/repo", "main")

        assert "git" in str(exc_info.value).lower()

    def test_empty_lines_in_output_skipped_then_raises(self) -> None:
        """Empty lines in git ls-remote output are skipped; ValueError raised if no match."""
        mock_result = MagicMock()
        mock_result.returncode = 0

        mock_result.stdout = "abc123\trefs/heads/other\n\ndef456\trefs/heads/another\n"

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(ValueError, match="not found on remote"):
                _list_branch_head("file:///some/repo", "main")

    def test_successful_branch_lookup_returns_sha(self) -> None:
        """Successful git ls-remote returns the SHA for the matching ref."""
        expected_sha = "abcdef1234567890abcdef1234567890abcdef12"
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = f"{expected_sha}\trefs/heads/main\n"

        with patch("subprocess.run", return_value=mock_result):
            sha = _list_branch_head("file:///some/repo", "main")

        assert sha == expected_sha


@pytest.mark.unit
class TestRunBranchPinnedErrorPaths:
    """run() converts _list_branch_head RuntimeError/ValueError to sys.exit(1)."""

    def test_run_exits_on_git_not_found(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """run() exits with code 1 when _list_branch_head raises RuntimeError (git not found)."""
        from kanon_cli.commands.outdated import run

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "GITBASE=file:///unused\n"
            "CLAUDE_MARKETPLACES_DIR=/tmp/.claude\n"
            "KANON_MARKETPLACE_INSTALL=false\n"
            "KANON_SOURCE_FOO_URL=file:///some/repo\n"
            "KANON_SOURCE_FOO_REF=main\n"
            "KANON_SOURCE_FOO_PATH=./foo\n"
            "KANON_SOURCE_FOO_NAME=FOO\n"
            "KANON_SOURCE_FOO_GITBASE=https://example.com\n"
        )

        args = _make_args(
            catalog_source="file:///fake/catalog@HEAD",
            kanon_file=str(kanon_file),
        )

        with patch(
            "kanon_cli.commands.outdated._list_branch_head",
            side_effect=RuntimeError("ERROR: git binary not found."),
        ):
            with pytest.raises(SystemExit) as exc_info:
                run(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "ERROR:" in captured.err

    def test_run_exits_on_branch_not_found(self, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture) -> None:
        """run() exits with code 1 when _list_branch_head raises ValueError (branch not found)."""
        from kanon_cli.commands.outdated import run

        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "GITBASE=file:///unused\n"
            "CLAUDE_MARKETPLACES_DIR=/tmp/.claude\n"
            "KANON_MARKETPLACE_INSTALL=false\n"
            "KANON_SOURCE_FOO_URL=file:///some/repo\n"
            "KANON_SOURCE_FOO_REF=main\n"
            "KANON_SOURCE_FOO_PATH=./foo\n"
            "KANON_SOURCE_FOO_NAME=FOO\n"
            "KANON_SOURCE_FOO_GITBASE=https://example.com\n"
        )

        args = _make_args(
            catalog_source="file:///fake/catalog@HEAD",
            kanon_file=str(kanon_file),
        )

        with patch(
            "kanon_cli.commands.outdated._list_branch_head",
            side_effect=ValueError("ERROR: Branch 'main' not found on remote."),
        ):
            with pytest.raises(SystemExit) as exc_info:
                run(args)

        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "ERROR:" in captured.err
