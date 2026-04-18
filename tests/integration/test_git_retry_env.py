"""Integration tests for git retry environment variable behavior.

Covers:
  - AC-TEST-001: KANON_GIT_RETRY_COUNT=0 disables retries on transient failure
  - AC-TEST-002: KANON_GIT_RETRY_COUNT=N retries up to N times
  - AC-TEST-003: KANON_GIT_RETRY_DELAY controls exponential backoff
  - AC-TEST-004: DNS failure and connection reset are retried per retry count

AC-FUNC-001: Retry env vars control the retry loop deterministically.
AC-CHANNEL-001: stdout vs stderr discipline is verified (no cross-channel leakage).

These tests exercise _run_ls_remote_with_retry() directly, patching only the
subprocess boundary. All env var values are injected via monkeypatch so the
tests remain deterministic and side-effect-free.
"""

from unittest.mock import MagicMock, patch

import pytest

from kanon_cli.repo.error import ManifestInvalidRevisionError
from kanon_cli.repo.project import _run_ls_remote_with_retry


# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

_REMOTE_URL = "https://example.com/org/manifest.git"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_transient_failure(stderr: str = "Connection reset by peer") -> MagicMock:
    """Return a mock CompletedProcess representing a transient ls-remote failure.

    Args:
        stderr: Error text to include in stderr output.

    Returns:
        Mock with returncode=1 and stderr containing the error text.
    """
    result = MagicMock()
    result.returncode = 1
    result.stdout = ""
    result.stderr = stderr
    return result


def _make_success(tags: tuple = ("refs/tags/1.0.0",)) -> MagicMock:
    """Return a mock CompletedProcess representing a successful ls-remote call.

    Args:
        tags: Tuple of tag strings to include in the ls-remote output.

    Returns:
        Mock with returncode=0 and stdout containing the tags.
    """
    lines = "\n".join(f"deadbeef{i:08x}\t{tag}" for i, tag in enumerate(tags))
    result = MagicMock()
    result.returncode = 0
    result.stdout = lines
    result.stderr = ""
    return result


# ---------------------------------------------------------------------------
# AC-TEST-001: KANON_GIT_RETRY_COUNT=0 disables retries on transient failure
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRetryCountZeroDisablesRetries:
    """AC-TEST-001: when KANON_GIT_RETRY_COUNT=0, no subprocess calls are
    made and ManifestInvalidRevisionError is raised immediately."""

    def test_retry_count_zero_raises_immediately(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_GIT_RETRY_COUNT=0 raises ManifestInvalidRevisionError without any subprocess call.

        With retry_count=0, range(1, 0+1) == range(1, 1) which is empty, so the
        loop body is never entered. No subprocess.run call is made. The function
        must still raise ManifestInvalidRevisionError.
        """
        monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "0")
        monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

        with patch("kanon_cli.repo.project.subprocess.run") as mock_run:
            with pytest.raises(ManifestInvalidRevisionError):
                _run_ls_remote_with_retry(_REMOTE_URL)

        assert mock_run.call_count == 0, (
            f"Expected subprocess.run to never be called when KANON_GIT_RETRY_COUNT=0, "
            f"but it was called {mock_run.call_count} time(s)."
        )

    def test_retry_count_zero_error_message_includes_attempt_count(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With KANON_GIT_RETRY_COUNT=0, the error message must report 0 attempts.

        The ManifestInvalidRevisionError message must include the attempt count
        so the caller understands why the operation failed immediately.
        """
        monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "0")
        monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

        with patch("kanon_cli.repo.project.subprocess.run"):
            with pytest.raises(ManifestInvalidRevisionError) as exc_info:
                _run_ls_remote_with_retry(_REMOTE_URL)

        error_message = str(exc_info.value)
        assert "0" in error_message, (
            f"Expected '0' (attempt count) in error message for KANON_GIT_RETRY_COUNT=0. Got: {error_message!r}"
        )

    def test_retry_count_zero_error_message_includes_remote_url(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With KANON_GIT_RETRY_COUNT=0, the error message must include the remote URL.

        The remote URL must appear in the ManifestInvalidRevisionError so the
        user can identify which repository was unreachable.
        """
        monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "0")
        monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

        with patch("kanon_cli.repo.project.subprocess.run"):
            with pytest.raises(ManifestInvalidRevisionError) as exc_info:
                _run_ls_remote_with_retry(_REMOTE_URL)

        assert _REMOTE_URL in str(exc_info.value), (
            f"Expected remote URL {_REMOTE_URL!r} in error message for KANON_GIT_RETRY_COUNT=0. Got: {exc_info.value!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-002: KANON_GIT_RETRY_COUNT=N retries up to N times
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRetryCountNRetriesUpToNTimes:
    """AC-TEST-002: KANON_GIT_RETRY_COUNT=N causes exactly N subprocess.run
    calls when all attempts fail with transient errors."""

    @pytest.mark.parametrize(
        "retry_count",
        [1, 2, 3, 5],
        ids=["n_1", "n_2", "n_3", "n_5"],
    )
    def test_retry_count_n_makes_exactly_n_calls_on_all_failures(
        self, monkeypatch: pytest.MonkeyPatch, retry_count: int
    ) -> None:
        """KANON_GIT_RETRY_COUNT=N results in exactly N subprocess calls on all-failure runs.

        When all ls-remote attempts fail with transient errors, subprocess.run
        is called exactly KANON_GIT_RETRY_COUNT times. The function raises
        ManifestInvalidRevisionError after exhausting all attempts.
        """
        monkeypatch.setenv("KANON_GIT_RETRY_COUNT", str(retry_count))
        monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

        failures = [_make_transient_failure("Connection timed out")] * retry_count

        with patch("kanon_cli.repo.project.subprocess.run", side_effect=failures) as mock_run:
            with patch("kanon_cli.repo.project.time.sleep"):
                with pytest.raises(ManifestInvalidRevisionError):
                    _run_ls_remote_with_retry(_REMOTE_URL)

        assert mock_run.call_count == retry_count, (
            f"Expected subprocess.run to be called exactly {retry_count} time(s) "
            f"(KANON_GIT_RETRY_COUNT={retry_count}), "
            f"but it was called {mock_run.call_count} time(s)."
        )

    def test_retry_count_n_stops_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_GIT_RETRY_COUNT=5: stops after 2 calls when the second attempt succeeds.

        When a retry attempt succeeds, no further calls are made. The function
        returns without raising ManifestInvalidRevisionError.
        """
        monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "5")
        monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

        side_effects = [_make_transient_failure(), _make_success()]

        with patch("kanon_cli.repo.project.subprocess.run", side_effect=side_effects) as mock_run:
            with patch("kanon_cli.repo.project.time.sleep"):
                result = _run_ls_remote_with_retry(_REMOTE_URL)

        assert result.returncode == 0, (
            f"Expected a successful CompletedProcess (returncode=0) but got returncode={result.returncode}."
        )
        assert mock_run.call_count == 2, (
            f"Expected subprocess.run to stop after 2 calls (1 failure + 1 success), "
            f"but it was called {mock_run.call_count} time(s)."
        )

    def test_retry_count_1_no_delay_on_single_attempt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_GIT_RETRY_COUNT=1 means one attempt with no inter-attempt delay.

        With exactly one attempt there are no retries, so time.sleep must never
        be called regardless of the KANON_GIT_RETRY_DELAY value.
        """
        monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "1")
        monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "5")

        with patch("kanon_cli.repo.project.subprocess.run", return_value=_make_transient_failure()):
            with patch("kanon_cli.repo.project.time.sleep") as mock_sleep:
                with pytest.raises(ManifestInvalidRevisionError):
                    _run_ls_remote_with_retry(_REMOTE_URL)

        mock_sleep.assert_not_called()

    def test_retry_count_error_message_includes_n(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ManifestInvalidRevisionError after N failures includes attempt count in message.

        The error message must state how many attempts were made so the operator
        can adjust KANON_GIT_RETRY_COUNT if needed.
        """
        retry_count = 4
        monkeypatch.setenv("KANON_GIT_RETRY_COUNT", str(retry_count))
        monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

        failures = [_make_transient_failure("network timeout")] * retry_count

        with patch("kanon_cli.repo.project.subprocess.run", side_effect=failures):
            with patch("kanon_cli.repo.project.time.sleep"):
                with pytest.raises(ManifestInvalidRevisionError) as exc_info:
                    _run_ls_remote_with_retry(_REMOTE_URL)

        error_message = str(exc_info.value)
        assert str(retry_count) in error_message, (
            f"Expected attempt count {retry_count!r} in error message, but got: {error_message!r}"
        )


# ---------------------------------------------------------------------------
# AC-TEST-003: KANON_GIT_RETRY_DELAY controls exponential backoff
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRetryDelayControlsExponentialBackoff:
    """AC-TEST-003: KANON_GIT_RETRY_DELAY sets the base delay for exponential
    backoff. Delay doubles each retry: attempt k sleeps base_delay * 2^(k-1)."""

    def test_retry_delay_base_seconds_used_for_first_sleep(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_GIT_RETRY_DELAY=2 causes the first inter-attempt sleep to be 2 seconds.

        The first sleep is base_delay * 2^(1-1) == base_delay * 1 == base_delay.
        """
        monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "3")
        monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "2")

        failures = [_make_transient_failure()] * 3

        with patch("kanon_cli.repo.project.subprocess.run", side_effect=failures):
            with patch("kanon_cli.repo.project.time.sleep") as mock_sleep:
                with pytest.raises(ManifestInvalidRevisionError):
                    _run_ls_remote_with_retry(_REMOTE_URL)

        assert mock_sleep.call_count == 2, (
            f"Expected time.sleep to be called 2 times (between 3 attempts), "
            f"but it was called {mock_sleep.call_count} time(s)."
        )
        first_delay = mock_sleep.call_args_list[0].args[0]
        assert first_delay == 2, (
            f"Expected first sleep delay to be 2 seconds (KANON_GIT_RETRY_DELAY=2), but got {first_delay!r}."
        )

    def test_retry_delay_doubles_on_second_retry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Exponential backoff: the second sleep is double the first.

        With KANON_GIT_RETRY_DELAY=3 and KANON_GIT_RETRY_COUNT=3, sleeps are 3
        and 6 seconds (3*2^0=3, 3*2^1=6).
        """
        monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "3")
        monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "3")

        failures = [_make_transient_failure()] * 3

        with patch("kanon_cli.repo.project.subprocess.run", side_effect=failures):
            with patch("kanon_cli.repo.project.time.sleep") as mock_sleep:
                with pytest.raises(ManifestInvalidRevisionError):
                    _run_ls_remote_with_retry(_REMOTE_URL)

        delays = [c.args[0] for c in mock_sleep.call_args_list]
        assert len(delays) == 2, f"Expected exactly 2 sleep calls for 3 attempts, but got {len(delays)}: {delays!r}"
        assert delays[0] == 3, f"Expected first delay to be 3 (base_delay=3, exponent=0), but got {delays[0]!r}."
        assert delays[1] == 6, f"Expected second delay to be 6 (base_delay=3, exponent=1), but got {delays[1]!r}."

    def test_retry_delay_zero_skips_sleep(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_GIT_RETRY_DELAY=0 results in all sleep calls receiving 0.

        A zero base delay means exponential backoff produces 0 * 2^k = 0 for
        every attempt. time.sleep is still called the correct number of times
        but with value 0.
        """
        monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "4")
        monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

        failures = [_make_transient_failure()] * 4

        with patch("kanon_cli.repo.project.subprocess.run", side_effect=failures):
            with patch("kanon_cli.repo.project.time.sleep") as mock_sleep:
                with pytest.raises(ManifestInvalidRevisionError):
                    _run_ls_remote_with_retry(_REMOTE_URL)

        delays = [c.args[0] for c in mock_sleep.call_args_list]
        assert len(delays) == 3, f"Expected 3 sleep calls for 4 attempts, but got {len(delays)}: {delays!r}"
        for delay in delays:
            assert delay == 0, f"Expected all sleep delays to be 0 when KANON_GIT_RETRY_DELAY=0, but got {delay!r}."

    def test_retry_delay_1_produces_canonical_1_2_sequence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """KANON_GIT_RETRY_DELAY=1 with 3 attempts produces sleep sequence [1, 2].

        This is the canonical pattern: base_delay * 2^(k-1) for k=1,2 gives
        1*1=1 and 1*2=2.
        """
        monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "3")
        monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "1")

        failures = [_make_transient_failure()] * 3

        with patch("kanon_cli.repo.project.subprocess.run", side_effect=failures):
            with patch("kanon_cli.repo.project.time.sleep") as mock_sleep:
                with pytest.raises(ManifestInvalidRevisionError):
                    _run_ls_remote_with_retry(_REMOTE_URL)

        delays = [c.args[0] for c in mock_sleep.call_args_list]
        assert delays == [1, 2], (
            f"Expected canonical sleep sequence [1, 2] for base_delay=1 with 3 attempts, but got {delays!r}."
        )


# ---------------------------------------------------------------------------
# AC-TEST-004: DNS failure and connection reset are retried per retry count
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTransientNetworkErrorsAreRetried:
    """AC-TEST-004: DNS resolution failures and connection resets are transient
    errors and must be retried up to KANON_GIT_RETRY_COUNT times."""

    @pytest.mark.parametrize(
        "stderr_text",
        [
            "fatal: unable to access 'https://example.com/': Could not resolve host: example.com",
            "fatal: unable to access 'https://example.com/': Could not resolve host",
            "Connection reset by peer",
            "fatal: read error: Connection reset by peer",
            "error: RPC failed; curl 56 Recv failure: Connection reset by peer",
        ],
        ids=[
            "dns_full_message",
            "dns_short_message",
            "connection_reset_bare",
            "connection_reset_fatal",
            "connection_reset_rpc",
        ],
    )
    def test_transient_error_retried_up_to_retry_count(self, monkeypatch: pytest.MonkeyPatch, stderr_text: str) -> None:
        """DNS and connection-reset failures are retried exactly KANON_GIT_RETRY_COUNT times.

        These error patterns are transient (not auth-related) and must be retried.
        When all KANON_GIT_RETRY_COUNT attempts fail, ManifestInvalidRevisionError
        is raised and subprocess.run was called exactly retry_count times.
        """
        retry_count = 3
        monkeypatch.setenv("KANON_GIT_RETRY_COUNT", str(retry_count))
        monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

        failures = [_make_transient_failure(stderr_text)] * retry_count

        with patch("kanon_cli.repo.project.subprocess.run", side_effect=failures) as mock_run:
            with patch("kanon_cli.repo.project.time.sleep"):
                with pytest.raises(ManifestInvalidRevisionError):
                    _run_ls_remote_with_retry(_REMOTE_URL)

        assert mock_run.call_count == retry_count, (
            f"Expected subprocess.run to be called {retry_count} time(s) for transient "
            f"error {stderr_text!r}, but it was called {mock_run.call_count} time(s)."
        )

    def test_dns_failure_then_success_resolves(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """DNS failure followed by success: the function returns the successful result.

        A transient DNS failure on the first attempt must not prevent a later
        successful attempt from being returned. No exception is raised.
        """
        monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "3")
        monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

        dns_failure = _make_transient_failure(
            "fatal: unable to access 'https://example.com/': Could not resolve host: example.com"
        )
        success = _make_success()

        with patch("kanon_cli.repo.project.subprocess.run", side_effect=[dns_failure, success]) as mock_run:
            with patch("kanon_cli.repo.project.time.sleep"):
                result = _run_ls_remote_with_retry(_REMOTE_URL)

        assert result.returncode == 0, (
            f"Expected returncode=0 after DNS failure then success, but got returncode={result.returncode}."
        )
        assert mock_run.call_count == 2, (
            f"Expected exactly 2 subprocess.run calls (DNS failure + success), but got {mock_run.call_count}."
        )

    def test_connection_reset_then_success_resolves(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Connection reset followed by success: the function returns the successful result.

        A transient connection reset on the first attempt must not prevent a
        later successful attempt from being returned.
        """
        monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "3")
        monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

        reset_failure = _make_transient_failure("Connection reset by peer")
        success = _make_success()

        with patch("kanon_cli.repo.project.subprocess.run", side_effect=[reset_failure, success]) as mock_run:
            with patch("kanon_cli.repo.project.time.sleep"):
                result = _run_ls_remote_with_retry(_REMOTE_URL)

        assert result.returncode == 0, (
            f"Expected returncode=0 after connection reset then success, but got returncode={result.returncode}."
        )
        assert mock_run.call_count == 2, (
            f"Expected exactly 2 subprocess.run calls (connection reset + success), but got {mock_run.call_count}."
        )

    def test_transient_errors_not_confused_with_auth_errors(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Transient network errors must not be mistaken for auth errors.

        DNS and connection-reset errors do not contain 'Authentication' or
        'Permission denied', so they must be retried rather than failing fast.
        This test verifies the distinguishing logic between error categories.
        """
        retry_count = 2
        monkeypatch.setenv("KANON_GIT_RETRY_COUNT", str(retry_count))
        monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

        dns_failure = _make_transient_failure("Could not resolve host: example.com")
        failures = [dns_failure] * retry_count

        with patch("kanon_cli.repo.project.subprocess.run", side_effect=failures) as mock_run:
            with patch("kanon_cli.repo.project.time.sleep"):
                with pytest.raises(ManifestInvalidRevisionError) as exc_info:
                    _run_ls_remote_with_retry(_REMOTE_URL)

        assert mock_run.call_count == retry_count, (
            f"DNS failure must be retried (not treated as auth error). "
            f"Expected {retry_count} calls, got {mock_run.call_count}."
        )
        assert "authentication" not in str(exc_info.value).lower(), (
            f"Error message for DNS failure must not mention 'authentication'. Got: {exc_info.value!r}"
        )


# ---------------------------------------------------------------------------
# AC-FUNC-001: Retry env vars control the retry loop deterministically
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRetryEnvVarsDeterministicControl:
    """AC-FUNC-001: The retry loop is controlled entirely by env vars. Changing
    KANON_GIT_RETRY_COUNT changes the number of subprocess calls with no other
    side effects."""

    def test_env_var_change_changes_call_count(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Different KANON_GIT_RETRY_COUNT values produce different subprocess call counts.

        Running the function twice with different KANON_GIT_RETRY_COUNT values
        must yield call counts matching each respective value. The loop is
        entirely driven by the env var with no internal state between calls.
        """
        transient = _make_transient_failure("network timeout")

        monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "2")
        monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")
        with patch("kanon_cli.repo.project.subprocess.run", return_value=transient) as mock_run_2:
            with patch("kanon_cli.repo.project.time.sleep"):
                with pytest.raises(ManifestInvalidRevisionError):
                    _run_ls_remote_with_retry(_REMOTE_URL)
        count_with_2 = mock_run_2.call_count

        monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "4")
        with patch("kanon_cli.repo.project.subprocess.run", return_value=transient) as mock_run_4:
            with patch("kanon_cli.repo.project.time.sleep"):
                with pytest.raises(ManifestInvalidRevisionError):
                    _run_ls_remote_with_retry(_REMOTE_URL)
        count_with_4 = mock_run_4.call_count

        assert count_with_2 == 2, f"Expected 2 subprocess calls for KANON_GIT_RETRY_COUNT=2, got {count_with_2}."
        assert count_with_4 == 4, f"Expected 4 subprocess calls for KANON_GIT_RETRY_COUNT=4, got {count_with_4}."

    def test_retry_delay_env_var_controls_sleep_duration(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Different KANON_GIT_RETRY_DELAY values produce different sleep durations.

        The sleep duration for the first retry is exactly KANON_GIT_RETRY_DELAY.
        Changing the env var must change the observed delay.
        """
        monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "2")
        monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "7")

        failures = [_make_transient_failure()] * 2

        with patch("kanon_cli.repo.project.subprocess.run", side_effect=failures):
            with patch("kanon_cli.repo.project.time.sleep") as mock_sleep:
                with pytest.raises(ManifestInvalidRevisionError):
                    _run_ls_remote_with_retry(_REMOTE_URL)

        mock_sleep.assert_called_once()
        observed_delay = mock_sleep.call_args.args[0]
        assert observed_delay == 7, (
            f"Expected sleep delay of 7 seconds (KANON_GIT_RETRY_DELAY=7), but got {observed_delay!r}."
        )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr discipline (no cross-channel leakage)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestStdoutStderrDiscipline:
    """AC-CHANNEL-001: _run_ls_remote_with_retry must not write to stdout.
    All diagnostic output routes through the logger (and ultimately stderr).
    """

    def test_no_stdout_output_on_retry_failure(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """_run_ls_remote_with_retry writes nothing to stdout on all-failure retry runs.

        The function must not use print() or otherwise write to stdout. All
        diagnostic output must route through the logger (stderr). capsys is
        used to intercept any direct stdout writes.
        """
        monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "2")
        monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

        failures = [_make_transient_failure("Connection timeout")] * 2

        with patch("kanon_cli.repo.project.subprocess.run", side_effect=failures):
            with patch("kanon_cli.repo.project.time.sleep"):
                with pytest.raises(ManifestInvalidRevisionError):
                    _run_ls_remote_with_retry(_REMOTE_URL)

        captured = capsys.readouterr()
        assert not captured.out.strip(), (
            f"Expected no stdout output from _run_ls_remote_with_retry, but got: {captured.out!r}"
        )

    def test_no_stdout_output_on_success(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
        """_run_ls_remote_with_retry writes nothing to stdout on a successful run.

        Even when the function returns successfully (returncode=0), nothing must
        be written to stdout.
        """
        monkeypatch.setenv("KANON_GIT_RETRY_COUNT", "1")
        monkeypatch.setenv("KANON_GIT_RETRY_DELAY", "0")

        with patch("kanon_cli.repo.project.subprocess.run", return_value=_make_success()):
            _run_ls_remote_with_retry(_REMOTE_URL)

        captured = capsys.readouterr()
        assert not captured.out.strip(), (
            f"Expected no stdout output from _run_ls_remote_with_retry on success, but got: {captured.out!r}"
        )
