"""Unit tests for _check_completion_errors_report in kanon_cli.commands.doctor.

Covers subcheck 7: completion errors report.

Parametrized cases:
- Absent log file: returns info finding "no completion errors recorded".
- Empty log file: returns info finding "no completion errors recorded".
- Log with fewer lines than the limit: returns all lines verbatim.
- Log with more lines than the limit: returns only the last N lines.
- Log with malformed lines: malformed lines are reported verbatim, not dropped.
"""

from __future__ import annotations

import pathlib

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_log(log_file: pathlib.Path, lines: list[str]) -> None:
    """Write lines to a log file, one per line.

    Args:
        log_file: Path to the log file to create.
        lines: Lines to write (without trailing newlines).
    """
    log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Tests: _check_completion_errors_report
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckCompletionErrorsReportAbsent:
    """Absent log file returns an info finding with no-errors message."""

    def test_absent_log_returns_info_finding(self, tmp_path: pathlib.Path) -> None:
        """_check_completion_errors_report returns info finding when log is absent.

        Args:
            tmp_path: Pytest temporary directory.
        """
        from kanon_cli.commands.doctor import _check_completion_errors_report

        # No log file created in tmp_path
        finding = _check_completion_errors_report(tmp_path, limit=5)

        assert finding is not None
        assert finding.kind == "info"
        assert "no completion errors recorded" in finding.message

    def test_absent_log_code_is_no_completion_errors(self, tmp_path: pathlib.Path) -> None:
        """Finding code is NO_COMPLETION_ERRORS when log is absent.

        Args:
            tmp_path: Pytest temporary directory.
        """
        from kanon_cli.commands.doctor import _check_completion_errors_report

        finding = _check_completion_errors_report(tmp_path, limit=5)

        assert finding.code == "NO_COMPLETION_ERRORS"


@pytest.mark.unit
class TestCheckCompletionErrorsReportEmpty:
    """Empty log file returns an info finding with no-errors message."""

    def test_empty_log_returns_info_finding(self, tmp_path: pathlib.Path) -> None:
        """_check_completion_errors_report returns info finding for an empty log.

        Args:
            tmp_path: Pytest temporary directory.
        """
        from kanon_cli.commands.doctor import _check_completion_errors_report

        log_file = tmp_path / "completion-errors.log"
        log_file.write_text("", encoding="utf-8")

        finding = _check_completion_errors_report(tmp_path, limit=5)

        assert finding.kind == "info"
        assert "no completion errors recorded" in finding.message

    def test_empty_log_code_is_no_completion_errors(self, tmp_path: pathlib.Path) -> None:
        """Finding code is NO_COMPLETION_ERRORS when log is empty.

        Args:
            tmp_path: Pytest temporary directory.
        """
        from kanon_cli.commands.doctor import _check_completion_errors_report

        log_file = tmp_path / "completion-errors.log"
        log_file.write_text("", encoding="utf-8")

        finding = _check_completion_errors_report(tmp_path, limit=5)

        assert finding.code == "NO_COMPLETION_ERRORS"


@pytest.mark.unit
class TestCheckCompletionErrorsReportPartial:
    """Log with fewer lines than the limit: returns all lines verbatim."""

    @pytest.mark.parametrize(
        "line_count",
        [1, 2, 4],
        ids=["one_line", "two_lines", "four_lines"],
    )
    def test_partial_log_returns_warn_finding(self, tmp_path: pathlib.Path, line_count: int) -> None:
        """When the log has fewer lines than the limit, returns a warn finding.

        Args:
            tmp_path: Pytest temporary directory.
            line_count: Number of log lines to write.
        """
        from kanon_cli.commands.doctor import _check_completion_errors_report

        lines = [f"2026-01-01T00:00:0{i}Z __complete_something Error: msg {i}" for i in range(line_count)]
        log_file = tmp_path / "completion-errors.log"
        _write_log(log_file, lines)

        finding = _check_completion_errors_report(tmp_path, limit=5)

        assert finding.kind == "warn"

    @pytest.mark.parametrize(
        "line_count",
        [1, 2, 4],
        ids=["one_line", "two_lines", "four_lines"],
    )
    def test_partial_log_includes_all_lines_in_message(self, tmp_path: pathlib.Path, line_count: int) -> None:
        """When the log has fewer lines than the limit, all lines appear in the message.

        Args:
            tmp_path: Pytest temporary directory.
            line_count: Number of log lines to write.
        """
        from kanon_cli.commands.doctor import _check_completion_errors_report

        lines = [f"2026-01-01T00:00:0{i}Z __complete_something Error: msg {i}" for i in range(line_count)]
        log_file = tmp_path / "completion-errors.log"
        _write_log(log_file, lines)

        finding = _check_completion_errors_report(tmp_path, limit=5)

        for line in lines:
            assert line in finding.message, (
                f"Expected line {line!r} to appear in the finding message but it did not: {finding.message!r}"
            )

    def test_partial_log_header_includes_count(self, tmp_path: pathlib.Path) -> None:
        """The finding message contains the header 'Recent completion errors (N):'.

        Args:
            tmp_path: Pytest temporary directory.
        """
        from kanon_cli.commands.doctor import _check_completion_errors_report

        lines = ["2026-01-01T00:00:00Z __complete_x ValueError: oops"]
        log_file = tmp_path / "completion-errors.log"
        _write_log(log_file, lines)

        finding = _check_completion_errors_report(tmp_path, limit=5)

        assert "Recent completion errors (1):" in finding.message


@pytest.mark.unit
class TestCheckCompletionErrorsReportFull:
    """Log with more lines than the limit: returns only the last N lines."""

    def test_full_log_returns_last_n_lines(self, tmp_path: pathlib.Path) -> None:
        """When the log exceeds the limit, only the last N lines appear in the message.

        Args:
            tmp_path: Pytest temporary directory.
        """
        from kanon_cli.commands.doctor import _check_completion_errors_report

        all_lines = [f"2026-01-01T00:00:0{i:02d}Z __complete_x Error: item {i}" for i in range(7)]
        log_file = tmp_path / "completion-errors.log"
        _write_log(log_file, all_lines)

        finding = _check_completion_errors_report(tmp_path, limit=5)

        # Last 5 lines must appear
        for line in all_lines[-5:]:
            assert line in finding.message, f"Expected last 5 lines to appear. Missing: {line!r}"

    def test_full_log_omits_early_lines(self, tmp_path: pathlib.Path) -> None:
        """When the log exceeds the limit, the first (non-recent) lines are omitted.

        Args:
            tmp_path: Pytest temporary directory.
        """
        from kanon_cli.commands.doctor import _check_completion_errors_report

        all_lines = [f"2026-01-01T00:00:0{i:02d}Z __complete_x Error: item {i}" for i in range(7)]
        log_file = tmp_path / "completion-errors.log"
        _write_log(log_file, all_lines)

        finding = _check_completion_errors_report(tmp_path, limit=5)

        # First 2 lines must NOT appear in the message
        for line in all_lines[:2]:
            assert line not in finding.message, f"Expected first lines to be omitted but found: {line!r}"

    def test_full_log_header_contains_limit(self, tmp_path: pathlib.Path) -> None:
        """The header shows N equal to the limit when log exceeds the limit.

        Args:
            tmp_path: Pytest temporary directory.
        """
        from kanon_cli.commands.doctor import _check_completion_errors_report

        all_lines = [f"2026-01-01T00:00:0{i:02d}Z __complete_x Error: item {i}" for i in range(7)]
        log_file = tmp_path / "completion-errors.log"
        _write_log(log_file, all_lines)

        finding = _check_completion_errors_report(tmp_path, limit=5)

        assert "Recent completion errors (5):" in finding.message

    def test_full_log_kind_is_warn(self, tmp_path: pathlib.Path) -> None:
        """Finding kind is warn when the log is non-empty.

        Args:
            tmp_path: Pytest temporary directory.
        """
        from kanon_cli.commands.doctor import _check_completion_errors_report

        all_lines = [f"2026-01-01T00:00:0{i:02d}Z __complete_x Error: item {i}" for i in range(7)]
        log_file = tmp_path / "completion-errors.log"
        _write_log(log_file, all_lines)

        finding = _check_completion_errors_report(tmp_path, limit=5)

        assert finding.kind == "warn"


@pytest.mark.unit
class TestCheckCompletionErrorsReportMalformed:
    """Malformed log lines are reported verbatim, not dropped."""

    def test_malformed_lines_included_verbatim(self, tmp_path: pathlib.Path) -> None:
        """Malformed lines in the log appear in the finding message unchanged.

        Args:
            tmp_path: Pytest temporary directory.
        """
        from kanon_cli.commands.doctor import _check_completion_errors_report

        lines = [
            "2026-01-01T00:00:00Z good-line Error: real error",
            "THIS IS MALFORMED AND HAS NO TIMESTAMP",
            "ALSO MALFORMED!!  @@@ ##",
        ]
        log_file = tmp_path / "completion-errors.log"
        _write_log(log_file, lines)

        finding = _check_completion_errors_report(tmp_path, limit=5)

        for line in lines:
            assert line in finding.message, (
                f"Expected malformed line {line!r} to appear verbatim in message. Message: {finding.message!r}"
            )

    def test_malformed_only_log_returns_warn_not_error(self, tmp_path: pathlib.Path) -> None:
        """A log with only malformed lines still produces a warn-level finding.

        Args:
            tmp_path: Pytest temporary directory.
        """
        from kanon_cli.commands.doctor import _check_completion_errors_report

        lines = ["COMPLETELY MALFORMED", "ANOTHER BAD LINE"]
        log_file = tmp_path / "completion-errors.log"
        _write_log(log_file, lines)

        finding = _check_completion_errors_report(tmp_path, limit=5)

        assert finding.kind == "warn"

    def test_log_not_mutated_after_read(self, tmp_path: pathlib.Path) -> None:
        """The log file is not mutated by _check_completion_errors_report.

        Args:
            tmp_path: Pytest temporary directory.
        """
        from kanon_cli.commands.doctor import _check_completion_errors_report

        lines = [
            "2026-01-01T00:00:00Z good Error: something",
            "2026-01-01T00:00:01Z another Error: something else",
        ]
        log_file = tmp_path / "completion-errors.log"
        _write_log(log_file, lines)
        original_content = log_file.read_text(encoding="utf-8")

        _check_completion_errors_report(tmp_path, limit=5)

        assert log_file.read_text(encoding="utf-8") == original_content, (
            "_check_completion_errors_report must not modify the log file"
        )


@pytest.mark.unit
class TestCheckCompletionErrorsReportLimitParametrized:
    """Limit parameter controls how many lines are reported."""

    @pytest.mark.parametrize(
        "total_lines, limit, expected_count",
        [
            (3, 5, 3),  # fewer than limit -- return all
            (5, 5, 5),  # exactly the limit -- return all
            (7, 5, 5),  # more than limit -- return last N
            (10, 3, 3),  # much more than limit -- return last N
        ],
        ids=["fewer_than_limit", "exactly_limit", "more_than_limit", "much_more"],
    )
    def test_limit_controls_reported_line_count(
        self,
        tmp_path: pathlib.Path,
        total_lines: int,
        limit: int,
        expected_count: int,
    ) -> None:
        """The limit parameter controls how many lines appear in the finding.

        The header 'Recent completion errors (N):' uses N = min(total, limit).

        Args:
            tmp_path: Pytest temporary directory.
            total_lines: Total number of lines to write to the log.
            limit: Line cap passed to _check_completion_errors_report.
            expected_count: Expected N in the header.
        """
        from kanon_cli.commands.doctor import _check_completion_errors_report

        lines = [f"2026-01-01T00:00:{i:02d}Z __complete_x Error: item {i}" for i in range(total_lines)]
        log_file = tmp_path / "completion-errors.log"
        _write_log(log_file, lines)

        finding = _check_completion_errors_report(tmp_path, limit=limit)

        assert f"Recent completion errors ({expected_count}):" in finding.message, (
            f"Expected header 'Recent completion errors ({expected_count}):' but got: {finding.message!r}"
        )


# ---------------------------------------------------------------------------
# AC-CYCLE-001: End-to-end cycle
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDoctorCommandEndToEndCycle:
    """AC-CYCLE-001: doctor_command emits errors log findings AND staleness warnings.

    Writes a completion-errors.log with seven lines AND an out-of-date bash
    completion script under tmp_path. Sets KANON_CACHE_DIR to tmp_path and
    runs doctor_command with a completion_generator that returns fresh content.
    Asserts:
    - stderr contains the last five log lines.
    - stderr contains a staleness warning for bash.
    """

    def test_cycle_errors_log_and_stale_script(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """End-to-end: doctor emits last 5 error lines AND stale bash warning.

        Args:
            tmp_path: Pytest temporary directory.
            monkeypatch: Pytest monkeypatch fixture.
            capsys: Pytest capture fixture for stdout/stderr.
        """
        import argparse

        from kanon_cli.commands.doctor import doctor_command

        # -- Arrange workspace files --
        kanon_file = tmp_path / ".kanon"
        kanon_file.write_text(
            "KANON_SOURCE_src_URL=https://example.com/org/repo.git\n"
            "KANON_SOURCE_src_REVISION=main\n"
            "KANON_SOURCE_src_PATH=repo-specs/meta.xml\n"
            "KANON_MARKETPLACE_INSTALL=false\n",
            encoding="utf-8",
        )

        # -- Create completion-errors.log with 7 lines --
        log_lines = [f"2026-01-01T00:00:0{i}Z __complete_sources ValueError: msg {i}" for i in range(7)]
        log_file = tmp_path / "completion-errors.log"
        _write_log(log_file, log_lines)

        # -- Create an out-of-date bash completion script --
        stale_bash_content = "# OLD STALE bash completion script\n"
        fresh_bash_content = "# NEW FRESH bash completion script\n"
        bash_script = tmp_path / "kanon_completion.bash"
        bash_script.write_text(stale_bash_content, encoding="utf-8")

        # Point KANON_CACHE_DIR at tmp_path
        monkeypatch.setenv("KANON_CACHE_DIR", str(tmp_path))

        # -- Build a minimal args namespace (no lockfile => subcheck 1 returns NO_LOCKFILE) --
        args = argparse.Namespace(
            kanon_file=str(kanon_file),
            lock_file=None,
            strict_drift=False,
            refresh_completion_cache=False,
            catalog_source=object(),  # _UNSET sentinel equivalent
        )

        def _fresh_generator(shell: str) -> str:
            """Return fresh bash completion content regardless of shell.

            Args:
                shell: Shell name (ignored -- returns fresh_bash_content always).

            Returns:
                Fresh completion script text.
            """
            return fresh_bash_content

        # Patch KANON_STATIC_COMPLETION_SEARCH_PATHS on the doctor module so
        # doctor_command discovers the stale bash script at tmp_path.
        import kanon_cli.commands.doctor as doctor_module

        monkeypatch.setattr(
            doctor_module,
            "KANON_STATIC_COMPLETION_SEARCH_PATHS",
            (("bash", str(bash_script)),),
        )

        # Invoke doctor_command with injected completion_generator
        result = doctor_command(
            args,
            completion_generator=_fresh_generator,
        )

        captured = capsys.readouterr()
        stderr = captured.err

        # -- Assert last 5 log lines appear in stderr --
        for line in log_lines[-5:]:
            assert line in stderr, f"Expected last-5 log line {line!r} to appear in stderr.\nstderr: {stderr!r}"

        # -- Assert first 2 log lines are NOT in stderr --
        for line in log_lines[:2]:
            assert line not in stderr, f"Expected early log line {line!r} to be absent from stderr.\nstderr: {stderr!r}"

        # -- Assert staleness warning for bash appears in stderr (via doctor_command) --
        assert "bash" in stderr, f"Expected 'bash' in stderr staleness warning.\nstderr: {stderr!r}"
        assert str(bash_script) in stderr, (
            f"Expected stale bash script path {str(bash_script)!r} in stderr staleness warning.\nstderr: {stderr!r}"
        )

        # -- doctor exits 0 (no error-level findings, only warn) --
        assert result == 0
