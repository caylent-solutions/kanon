"""Integration tests for git fault injection scenarios.

Covers:
  - AC-TEST-001: git binary missing exits 1 with actionable message
  - AC-TEST-002: bad URL produces error including URL in stderr
  - AC-TEST-003: bad revision produces error including revision name
  - AC-TEST-004: HTTPS auth failure (401) does not trigger retries

AC-FUNC-001: Git failures surface stderr context and distinguish transient vs
             permanent errors.
AC-CHANNEL-001: stdout vs stderr discipline is verified (no cross-channel leakage).
"""

import os
import pathlib
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from kanon_cli.repo.project import _run_ls_remote_with_retry
from kanon_cli.repo.error import ManifestInvalidRevisionError
from kanon_cli.version import _list_tags, resolve_version


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SRC_DIR = _REPO_ROOT / "src"

_TEST_URL = "https://example.com/org/manifest.git"
_TEST_BAD_REVISION = "refs/tags/does-not-exist/>=99.0.0"

_MINIMAL_KANONENV_CONTENT = (
    "GITBASE=https://example.com/\n"
    "KANON_MARKETPLACE_INSTALL=false\n"
    f"KANON_SOURCE_test_URL={_TEST_URL}\n"
    "KANON_SOURCE_test_REVISION=~=1.0.0\n"
    "KANON_SOURCE_test_PATH=repo-specs/default.xml\n"
)


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------


def _run_kanon_subprocess(
    *args: str,
    cwd: "pathlib.Path | None" = None,
    extra_env: "dict[str, str] | None" = None,
) -> subprocess.CompletedProcess:
    """Invoke kanon_cli in a subprocess and return the completed process.

    Ensures PYTHONPATH points at the current source tree so the subprocess
    uses the locally checked-out kanon_cli rather than any installed version.
    Sets REPO_TRACE=0 to suppress trace file writes during tests.

    Args:
        *args: CLI arguments passed after ``python -m kanon_cli``.
        cwd: Working directory for the subprocess. Defaults to None.
        extra_env: Additional environment variables merged on top of os.environ.

    Returns:
        The CompletedProcess object (check=False).
    """
    env = dict(os.environ)
    existing_pythonpath = env.get("PYTHONPATH", "")
    src_str = str(_SRC_DIR)
    path_entries = [src_str] + [p for p in existing_pythonpath.split(os.pathsep) if p and p != src_str]
    env["PYTHONPATH"] = os.pathsep.join(path_entries)
    env.setdefault("REPO_TRACE", "0")
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        [sys.executable, "-m", "kanon_cli", *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=str(cwd) if cwd is not None else None,
        env=env,
    )


def _write_kanonenv(directory: pathlib.Path, content: str = _MINIMAL_KANONENV_CONTENT) -> pathlib.Path:
    """Write a .kanon file in directory and return its absolute path.

    Args:
        directory: Directory in which to create the .kanon file.
        content: Content to write to the file. Defaults to the minimal valid content.

    Returns:
        Absolute path to the created .kanon file.
    """
    kanonenv = directory / ".kanon"
    kanonenv.write_text(content)
    return kanonenv


# ---------------------------------------------------------------------------
# AC-TEST-001: git binary missing exits 1 with actionable message
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGitBinaryMissing:
    """AC-TEST-001: when git is not in PATH, operations fail with exit code 1
    and an actionable message on stderr rather than an unhandled traceback."""

    def test_list_tags_git_missing_raises_actionable_error(self) -> None:
        """_list_tags raises SystemExit with code 1 when git binary is not found.

        When subprocess.run raises FileNotFoundError (git not in PATH), the
        caller must receive a SystemExit(1) with an error message that tells
        the user git is not installed, not a raw FileNotFoundError traceback.
        """
        with patch("kanon_cli.version.subprocess.run", side_effect=FileNotFoundError("git")):
            with pytest.raises(SystemExit) as exc_info:
                _list_tags(_TEST_URL)
        assert exc_info.value.code == 1

    def test_list_tags_git_missing_actionable_message_on_stderr(self, capsys) -> None:
        """_list_tags writes an actionable 'git not found' message to stderr when git is missing."""
        with patch("kanon_cli.version.subprocess.run", side_effect=FileNotFoundError("git")):
            with pytest.raises(SystemExit):
                _list_tags(_TEST_URL)
        captured = capsys.readouterr()
        assert "git" in captured.err.lower(), (
            f"Expected 'git' in stderr error message for missing binary. Got stderr={captured.err!r}"
        )
        assert captured.err.strip(), "Expected non-empty stderr when git binary is missing"

    def test_list_tags_git_missing_no_traceback_on_stderr(self, capsys) -> None:
        """_list_tags must not emit a raw Python traceback to stderr for missing git."""
        with patch("kanon_cli.version.subprocess.run", side_effect=FileNotFoundError("git")):
            with pytest.raises(SystemExit):
                _list_tags(_TEST_URL)
        captured = capsys.readouterr()
        assert "Traceback" not in captured.err, (
            f"Raw traceback must not appear in stderr for missing git binary. Got stderr={captured.err!r}"
        )

    def test_run_ls_remote_with_retry_git_missing_raises_manifest_error(self) -> None:
        """_run_ls_remote_with_retry raises ManifestInvalidRevisionError when git is missing.

        A FileNotFoundError from subprocess is a permanent failure (git is not
        installed), so it must be converted to ManifestInvalidRevisionError with
        an actionable message rather than propagating as a raw exception.
        """
        with patch("kanon_cli.repo.project.subprocess.run", side_effect=FileNotFoundError("git")):
            with pytest.raises(ManifestInvalidRevisionError) as exc_info:
                _run_ls_remote_with_retry(_TEST_URL)
        assert "git" in str(exc_info.value).lower(), (
            f"ManifestInvalidRevisionError message must mention 'git'. Got: {exc_info.value!r}"
        )

    def test_run_ls_remote_with_retry_git_missing_no_retries(self) -> None:
        """_run_ls_remote_with_retry must not retry when git binary is not found.

        FileNotFoundError is a permanent failure -- git is simply not installed.
        Retrying cannot fix it, so the function must fail immediately.
        """
        call_count = 0

        def _missing_git(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise FileNotFoundError("git")

        with patch("kanon_cli.repo.project.subprocess.run", side_effect=_missing_git):
            with pytest.raises(ManifestInvalidRevisionError):
                _run_ls_remote_with_retry(_TEST_URL)

        assert call_count == 1, (
            f"Expected exactly 1 subprocess call for FileNotFoundError (no retries), got {call_count}"
        )

    def test_install_git_missing_exits_1_subprocess(self, tmp_path: pathlib.Path) -> None:
        """kanon install exits 1 when git binary is missing (via subprocess invocation).

        AC-CHANNEL-001: error text must appear on stderr, not stdout.
        """
        kanonenv = _write_kanonenv(tmp_path)
        env = dict(os.environ)
        # Remove git from PATH by setting a PATH that only contains a temp directory
        # with no git binary.
        empty_bin_dir = tmp_path / "empty_bin"
        empty_bin_dir.mkdir()
        env["PATH"] = str(empty_bin_dir)

        existing_pythonpath = env.get("PYTHONPATH", "")
        src_str = str(_SRC_DIR)
        path_entries = [src_str] + [p for p in existing_pythonpath.split(os.pathsep) if p and p != src_str]
        env["PYTHONPATH"] = os.pathsep.join(path_entries)
        env["REPO_TRACE"] = "0"

        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "install", str(kanonenv)],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )

        assert result.returncode == 1, (
            f"Expected exit code 1 when git is missing. Got {result.returncode}.\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert result.stderr.strip(), "Expected non-empty stderr when git binary is missing"


# ---------------------------------------------------------------------------
# AC-TEST-002: bad URL produces error including URL in stderr
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestBadUrl:
    """AC-TEST-002: when a bad (unreachable) URL is given, the error message
    includes the URL so the user knows which source failed."""

    @pytest.mark.parametrize(
        "stderr_text",
        [
            "fatal: repository 'https://example.com/bad.git/' not found",
            "fatal: unable to access 'https://example.com/bad.git/': Could not resolve host",
        ],
    )
    def test_list_tags_bad_url_includes_url_in_stderr(self, capsys, stderr_text: str) -> None:
        """_list_tags writes the URL to stderr when git ls-remote fails for a bad URL."""
        bad_url = "https://example.com/bad.git"
        mock_result = MagicMock(returncode=128, stdout="", stderr=stderr_text)
        with patch("kanon_cli.version.subprocess.run", return_value=mock_result):
            with pytest.raises(SystemExit):
                _list_tags(bad_url)
        captured = capsys.readouterr()
        assert bad_url in captured.err, f"Expected the URL {bad_url!r} to appear in stderr. Got stderr={captured.err!r}"

    def test_list_tags_bad_url_exits_1(self) -> None:
        """_list_tags exits with code 1 when git ls-remote returns non-zero for a bad URL."""
        mock_result = MagicMock(returncode=128, stdout="", stderr="fatal: repository not found")
        with patch("kanon_cli.version.subprocess.run", return_value=mock_result):
            with pytest.raises(SystemExit) as exc_info:
                _list_tags(_TEST_URL)
        assert exc_info.value.code == 1, f"Expected SystemExit(1) for bad URL, got SystemExit({exc_info.value.code})"

    def test_list_tags_bad_url_no_cross_channel_leakage(self, capsys) -> None:
        """AC-CHANNEL-001: error text for bad URL appears on stderr only, not stdout."""
        mock_result = MagicMock(returncode=128, stdout="", stderr="fatal: not found")
        with patch("kanon_cli.version.subprocess.run", return_value=mock_result):
            with pytest.raises(SystemExit):
                _list_tags(_TEST_URL)
        captured = capsys.readouterr()
        assert not captured.out.strip(), (
            f"Error text must not appear on stdout for bad URL. Got stdout={captured.out!r}"
        )

    def test_run_ls_remote_with_retry_bad_url_includes_url_in_error(self) -> None:
        """_run_ls_remote_with_retry error message includes the remote URL after all retries fail."""
        mock_result = MagicMock(returncode=128, stdout="", stderr="fatal: repository not found")
        with patch("kanon_cli.repo.project.subprocess.run", return_value=mock_result):
            with patch.dict(os.environ, {"KANON_GIT_RETRY_COUNT": "1", "KANON_GIT_RETRY_DELAY": "0"}):
                with pytest.raises(ManifestInvalidRevisionError) as exc_info:
                    _run_ls_remote_with_retry(_TEST_URL)
        assert _TEST_URL in str(exc_info.value), (
            f"Expected URL {_TEST_URL!r} in ManifestInvalidRevisionError message. Got: {exc_info.value!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: bad revision produces error including revision name
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestBadRevision:
    """AC-TEST-003: when no tags match the revision constraint, the error message
    includes the revision string so the user knows what constraint failed."""

    def test_resolve_version_bad_revision_includes_constraint_in_stderr(self, capsys) -> None:
        """resolve_version writes the bad revision constraint to stderr when no tags match."""
        bad_revision = ">=99.0.0"
        tags = ["refs/tags/1.0.0", "refs/tags/1.1.0"]
        mock_result = MagicMock(returncode=0, stdout="\n".join(f"abc123\t{t}" for t in tags), stderr="")
        with patch("kanon_cli.version.subprocess.run", return_value=mock_result):
            with pytest.raises(SystemExit):
                resolve_version(_TEST_URL, bad_revision)
        captured = capsys.readouterr()
        assert bad_revision in captured.err, (
            f"Expected the revision constraint {bad_revision!r} to appear in stderr. Got stderr={captured.err!r}"
        )

    def test_resolve_version_bad_revision_exits_1(self) -> None:
        """resolve_version exits with code 1 when no tags match the given revision constraint."""
        bad_revision = ">=99.0.0"
        tags = ["refs/tags/1.0.0"]
        mock_result = MagicMock(returncode=0, stdout="\n".join(f"abc123\t{t}" for t in tags), stderr="")
        with patch("kanon_cli.version.subprocess.run", return_value=mock_result):
            with pytest.raises(SystemExit) as exc_info:
                resolve_version(_TEST_URL, bad_revision)
        assert exc_info.value.code == 1, (
            f"Expected SystemExit(1) for bad revision, got SystemExit({exc_info.value.code})"
        )

    def test_resolve_version_bad_revision_no_cross_channel_leakage(self, capsys) -> None:
        """AC-CHANNEL-001: bad revision error appears on stderr only, not stdout."""
        bad_revision = ">=99.0.0"
        tags = ["refs/tags/1.0.0"]
        mock_result = MagicMock(returncode=0, stdout="\n".join(f"abc123\t{t}" for t in tags), stderr="")
        with patch("kanon_cli.version.subprocess.run", return_value=mock_result):
            with pytest.raises(SystemExit):
                resolve_version(_TEST_URL, bad_revision)
        captured = capsys.readouterr()
        assert not captured.out.strip(), (
            f"Error text must not appear on stdout for bad revision. Got stdout={captured.out!r}"
        )

    def test_resolve_version_namespaced_bad_revision_includes_constraint(self, capsys) -> None:
        """resolve_version includes the full namespaced revision in the stderr error message."""
        bad_revision = "refs/tags/dev/python/my-lib/>=99.0.0"
        tags = ["refs/tags/dev/python/my-lib/1.0.0"]
        mock_result = MagicMock(returncode=0, stdout="\n".join(f"abc123\t{t}" for t in tags), stderr="")
        with patch("kanon_cli.version.subprocess.run", return_value=mock_result):
            with pytest.raises(SystemExit):
                resolve_version(_TEST_URL, bad_revision)
        captured = capsys.readouterr()
        # The constraint portion of the revision must appear in the error message.
        assert "99.0.0" in captured.err, (
            f"Expected the version constraint to appear in stderr. Got stderr={captured.err!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: HTTPS auth failure does not trigger retries
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestHttpsAuthFailureNoRetry:
    """AC-TEST-004: authentication failures (401 / permission denied) must not
    be retried -- retrying could lock out the user's credentials."""

    @pytest.mark.parametrize(
        "auth_stderr",
        [
            "fatal: Authentication failed for 'https://example.com/'",
            "Permission denied (publickey)",
            "fatal: could not read Username -- Authentication required",
        ],
    )
    def test_auth_failure_raises_immediately_without_retry(self, auth_stderr: str) -> None:
        """_run_ls_remote_with_retry raises ManifestInvalidRevisionError immediately on auth failure.

        Authentication errors must never be retried. The function must raise on the
        first failure when the stderr output matches any GIT_AUTH_ERROR_PATTERNS pattern.
        """
        call_count = 0

        def _auth_failure(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return MagicMock(returncode=128, stdout="", stderr=auth_stderr)

        with patch("kanon_cli.repo.project.subprocess.run", side_effect=_auth_failure):
            with patch.dict(os.environ, {"KANON_GIT_RETRY_COUNT": "3", "KANON_GIT_RETRY_DELAY": "0"}):
                with pytest.raises(ManifestInvalidRevisionError):
                    _run_ls_remote_with_retry(_TEST_URL)

        assert call_count == 1, (
            f"Expected exactly 1 subprocess call for auth failure (no retries). "
            f"Got {call_count} calls. stderr was: {auth_stderr!r}"
        )

    @pytest.mark.parametrize(
        "auth_stderr",
        [
            "fatal: Authentication failed for 'https://example.com/'",
            "Permission denied (publickey)",
        ],
    )
    def test_auth_failure_error_message_includes_auth_context(self, auth_stderr: str) -> None:
        """ManifestInvalidRevisionError message for auth failure includes 'authentication' context.

        The error distinguishes auth failures from transient network failures so
        the user knows not to retry and to check credentials instead.
        """
        mock_result = MagicMock(returncode=128, stdout="", stderr=auth_stderr)
        with patch("kanon_cli.repo.project.subprocess.run", return_value=mock_result):
            with pytest.raises(ManifestInvalidRevisionError) as exc_info:
                _run_ls_remote_with_retry(_TEST_URL)
        assert "authentication" in str(exc_info.value).lower(), (
            f"Expected 'authentication' in error message for auth failure. Got: {exc_info.value!r}"
        )

    def test_transient_failure_does_retry(self) -> None:
        """Non-auth failures ARE retried up to KANON_GIT_RETRY_COUNT times.

        This verifies the distinction between transient errors (retried) and
        auth errors (not retried).
        """
        call_count = 0

        def _transient_failure(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return MagicMock(returncode=1, stdout="", stderr="fatal: network timeout")

        with patch("kanon_cli.repo.project.subprocess.run", side_effect=_transient_failure):
            with patch.dict(os.environ, {"KANON_GIT_RETRY_COUNT": "3", "KANON_GIT_RETRY_DELAY": "0"}):
                with pytest.raises(ManifestInvalidRevisionError):
                    _run_ls_remote_with_retry(_TEST_URL)

        assert call_count == 3, f"Expected 3 subprocess calls for transient failure (with retries). Got {call_count}"

    def test_auth_failure_error_message_includes_url(self) -> None:
        """ManifestInvalidRevisionError for auth failure includes the remote URL."""
        auth_stderr = "fatal: Authentication failed for 'https://example.com/'"
        mock_result = MagicMock(returncode=128, stdout="", stderr=auth_stderr)
        with patch("kanon_cli.repo.project.subprocess.run", return_value=mock_result):
            with pytest.raises(ManifestInvalidRevisionError) as exc_info:
                _run_ls_remote_with_retry(_TEST_URL)
        assert _TEST_URL in str(exc_info.value), (
            f"Expected URL {_TEST_URL!r} in error message for auth failure. Got: {exc_info.value!r}"
        )
