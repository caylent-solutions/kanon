"""Unit tests for kanon_cli.core.git_runner.

Covers:
- run_git_ls_remote: success path returns (0, stdout, stderr)
- run_git_ls_remote: retry-exhaustion with no time.sleep calls
- run_git_ls_remote: subprocess.TimeoutExpired returns exit code 124
- run_git_ls_remote: auth-error pattern skips retry immediately
- KANON_GIT_LS_REMOTE_TIMEOUT constant read from constants (via _env_int)

AC-4 helper tests: verify git_runner module exists and is importable.
"""

from __future__ import annotations

import subprocess

import pytest


@pytest.mark.unit
class TestGitRunnerModuleExists:
    """git_runner module must exist and be importable from kanon_cli.core."""

    def test_module_is_importable(self) -> None:
        """kanon_cli.core.git_runner can be imported without error."""
        import kanon_cli.core.git_runner as git_runner

        assert git_runner is not None

    def test_run_git_ls_remote_is_callable(self) -> None:
        """run_git_ls_remote is a callable exported from git_runner."""
        from kanon_cli.core.git_runner import run_git_ls_remote

        assert callable(run_git_ls_remote)


@pytest.mark.unit
class TestRunGitLsRemoteSuccess:
    """run_git_ls_remote returns (0, stdout, stderr) on a successful subprocess call."""

    def test_success_returns_zero_exit_code(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When subprocess.run returns 0, run_git_ls_remote returns exit code 0."""
        fake_result = subprocess.CompletedProcess(
            args=["git", "ls-remote"],
            returncode=0,
            stdout="abc\trefs/heads/main\n",
            stderr="",
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_result)

        from kanon_cli.core.git_runner import run_git_ls_remote

        code, out, err = run_git_ls_remote(
            ["git", "ls-remote", "https://example.com/repo.git", "HEAD"],
            timeout=30,
            retry_count=1,
        )

        assert code == 0
        assert out == "abc\trefs/heads/main\n"
        assert err == ""

    def test_success_stdout_is_forwarded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """stdout from subprocess is forwarded verbatim in the return tuple."""
        expected_stdout = "deadbeef\trefs/tags/1.0.0\n"
        fake_result = subprocess.CompletedProcess(
            args=["git", "ls-remote"],
            returncode=0,
            stdout=expected_stdout,
            stderr="",
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_result)

        from kanon_cli.core.git_runner import run_git_ls_remote

        _, out, _ = run_git_ls_remote(
            ["git", "ls-remote", "https://example.com/repo.git", "HEAD"],
            timeout=30,
            retry_count=1,
        )

        assert out == expected_stdout

    def test_only_one_subprocess_call_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A successful first attempt results in exactly one subprocess call (no retry)."""
        call_count = 0

        def _fake_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return subprocess.CompletedProcess(args=args[0], returncode=0, stdout="", stderr="")

        monkeypatch.setattr(subprocess, "run", _fake_run)

        from kanon_cli.core.git_runner import run_git_ls_remote

        run_git_ls_remote(
            ["git", "ls-remote", "https://example.com/repo.git"],
            timeout=30,
            retry_count=3,
        )

        assert call_count == 1


@pytest.mark.unit
class TestRetryExhaustionNoSleep:
    """run_git_ls_remote retries up to retry_count on non-auth failures; never calls time.sleep."""

    def test_retry_exhaustion_calls_subprocess_retry_count_times(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With retry_count=3 and all attempts failing, subprocess.run is called exactly 3 times."""
        call_count = 0

        def _fake_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return subprocess.CompletedProcess(args=args[0], returncode=1, stdout="", stderr="transient")

        monkeypatch.setattr(subprocess, "run", _fake_run)

        from kanon_cli.core.git_runner import run_git_ls_remote

        run_git_ls_remote(
            ["git", "ls-remote", "https://example.com/repo.git"],
            timeout=30,
            retry_count=3,
        )

        assert call_count == 3

    def test_retry_exhaustion_returns_last_exit_code(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """After retry exhaustion, the last non-zero exit code is returned."""
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **kw: subprocess.CompletedProcess(args=a[0], returncode=128, stdout="", stderr="fatal"),
        )

        from kanon_cli.core.git_runner import run_git_ls_remote

        code, _, _ = run_git_ls_remote(
            ["git", "ls-remote", "https://example.com/repo.git"],
            timeout=30,
            retry_count=2,
        )

        assert code == 128

    def test_no_sleep_called_between_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """run_git_ls_remote never calls time.sleep, even with multiple retry attempts."""
        import time

        sleep_calls: list[float] = []
        original_sleep = time.sleep

        def _tracking_sleep(delay: float) -> None:
            sleep_calls.append(delay)
            original_sleep(0)

        monkeypatch.setattr(time, "sleep", _tracking_sleep)
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **kw: subprocess.CompletedProcess(args=a[0], returncode=1, stdout="", stderr="transient"),
        )

        from kanon_cli.core.git_runner import run_git_ls_remote

        run_git_ls_remote(
            ["git", "ls-remote", "https://example.com/repo.git"],
            timeout=30,
            retry_count=3,
        )

        assert sleep_calls == [], f"time.sleep was called {len(sleep_calls)} time(s); expected 0"

    def test_retry_count_one_means_no_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """retry_count=1 means exactly one attempt with no retry on failure."""
        call_count = 0

        def _fake_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return subprocess.CompletedProcess(args=args[0], returncode=1, stdout="", stderr="fail")

        monkeypatch.setattr(subprocess, "run", _fake_run)

        from kanon_cli.core.git_runner import run_git_ls_remote

        run_git_ls_remote(
            ["git", "ls-remote", "https://example.com/repo.git"],
            timeout=30,
            retry_count=1,
        )

        assert call_count == 1


@pytest.mark.unit
class TestTimeoutErrorPath:
    """run_git_ls_remote returns exit code 124 on subprocess.TimeoutExpired."""

    def test_timeout_returns_exit_code_124(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """subprocess.TimeoutExpired causes run_git_ls_remote to return exit code 124."""

        def _fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=1)

        monkeypatch.setattr(subprocess, "run", _fake_run)

        from kanon_cli.core.git_runner import run_git_ls_remote

        code, _, err = run_git_ls_remote(
            ["git", "ls-remote", "https://example.com/repo.git"],
            timeout=1,
            retry_count=1,
        )

        assert code == 124

    def test_timeout_stderr_contains_timed_out(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The stderr returned on timeout contains an informative 'timed out' message."""

        def _fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=5)

        monkeypatch.setattr(subprocess, "run", _fake_run)

        from kanon_cli.core.git_runner import run_git_ls_remote

        _, _, err = run_git_ls_remote(
            ["git", "ls-remote", "https://example.com/repo.git"],
            timeout=5,
            retry_count=1,
        )

        assert "timed out" in err

    def test_timeout_retries_up_to_retry_count(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """subprocess.TimeoutExpired retries up to retry_count attempts."""
        call_count = 0

        def _fake_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=1)

        monkeypatch.setattr(subprocess, "run", _fake_run)

        from kanon_cli.core.git_runner import run_git_ls_remote

        run_git_ls_remote(
            ["git", "ls-remote", "https://example.com/repo.git"],
            timeout=1,
            retry_count=3,
        )

        assert call_count == 3

    def test_timeout_no_sleep_between_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """No time.sleep is called between timeout retries."""
        import time

        sleep_calls: list[float] = []
        original_sleep = time.sleep

        def _tracking_sleep(delay: float) -> None:
            sleep_calls.append(delay)
            original_sleep(0)

        monkeypatch.setattr(time, "sleep", _tracking_sleep)

        def _fake_run(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd=args[0], timeout=1)

        monkeypatch.setattr(subprocess, "run", _fake_run)

        from kanon_cli.core.git_runner import run_git_ls_remote

        run_git_ls_remote(
            ["git", "ls-remote", "https://example.com/repo.git"],
            timeout=1,
            retry_count=2,
        )

        assert sleep_calls == [], f"time.sleep was called {len(sleep_calls)} time(s); expected 0"


@pytest.mark.unit
class TestAuthErrorSkipsRetry:
    """Auth-error patterns in stderr cause run_git_ls_remote to skip retries immediately."""

    @pytest.mark.parametrize(
        "auth_pattern",
        [
            "Authentication failed",
            "Permission denied (publickey)",
            "Permission denied",
        ],
    )
    def test_auth_error_skips_retry(self, monkeypatch: pytest.MonkeyPatch, auth_pattern: str) -> None:
        """When stderr contains an auth-error pattern, only one subprocess call is made."""
        call_count = 0

        def _fake_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return subprocess.CompletedProcess(args=args[0], returncode=128, stdout="", stderr=auth_pattern)

        monkeypatch.setattr(subprocess, "run", _fake_run)

        from kanon_cli.core.git_runner import run_git_ls_remote

        run_git_ls_remote(
            ["git", "ls-remote", "https://example.com/repo.git"],
            timeout=30,
            retry_count=3,
        )

        assert call_count == 1, f"Expected 1 subprocess call for auth pattern {auth_pattern!r}; got {call_count}"

    def test_auth_error_exit_code_propagated(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The non-zero exit code from an auth-error attempt is propagated to the caller."""
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda *a, **kw: subprocess.CompletedProcess(
                args=a[0], returncode=128, stdout="", stderr="Permission denied"
            ),
        )

        from kanon_cli.core.git_runner import run_git_ls_remote

        code, _, err = run_git_ls_remote(
            ["git", "ls-remote", "https://example.com/repo.git"],
            timeout=30,
            retry_count=3,
        )

        assert code == 128
        assert "Permission denied" in err


@pytest.mark.unit
class TestKanonGitLsRemoteTimeoutConstant:
    """KANON_GIT_LS_REMOTE_TIMEOUT must exist in constants.py and be read via _env_int."""

    def test_constant_is_importable(self) -> None:
        """KANON_GIT_LS_REMOTE_TIMEOUT is importable from kanon_cli.constants."""
        from kanon_cli.constants import KANON_GIT_LS_REMOTE_TIMEOUT

        assert KANON_GIT_LS_REMOTE_TIMEOUT is not None

    def test_constant_is_positive_integer(self) -> None:
        """KANON_GIT_LS_REMOTE_TIMEOUT is a positive integer."""
        from kanon_cli.constants import KANON_GIT_LS_REMOTE_TIMEOUT

        assert isinstance(KANON_GIT_LS_REMOTE_TIMEOUT, int)
        assert KANON_GIT_LS_REMOTE_TIMEOUT > 0

    def test_constant_default_is_30(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_GIT_LS_REMOTE_TIMEOUT defaults to 30 when env var is unset."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.delenv("KANON_GIT_LS_REMOTE_TIMEOUT", raising=False)
        importlib.reload(constants)

        assert constants.KANON_GIT_LS_REMOTE_TIMEOUT == 30

    def test_constant_reads_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_GIT_LS_REMOTE_TIMEOUT reflects the KANON_GIT_LS_REMOTE_TIMEOUT env var."""
        import importlib

        import kanon_cli.constants as constants

        monkeypatch.setenv("KANON_GIT_LS_REMOTE_TIMEOUT", "60")
        importlib.reload(constants)

        assert constants.KANON_GIT_LS_REMOTE_TIMEOUT == 60
