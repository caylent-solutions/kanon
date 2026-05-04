# Copyright (C) 2023 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit test for repo_logging module."""

import contextlib
import io
import logging
import unittest

import pytest
from unittest import mock

from kanon_cli.repo.color import SetDefaultColoring
from kanon_cli.repo.error import RepoExitError
from kanon_cli.repo.repo_logging import RepoLogger


class TestRepoLogger(unittest.TestCase):
    @mock.patch.object(RepoLogger, "error")
    def test_log_aggregated_errors_logs_aggregated_errors(self, mock_error):
        """Test if log_aggregated_errors logs a list of aggregated errors."""
        logger = RepoLogger(__name__)
        logger.log_aggregated_errors(
            RepoExitError(
                aggregate_errors=[
                    Exception("foo"),
                    Exception("bar"),
                    Exception("baz"),
                    Exception("hello"),
                    Exception("world"),
                    Exception("test"),
                ]
            )
        )

        mock_error.assert_has_calls(
            [
                mock.call("=" * 80),
                mock.call(
                    "Repo command failed due to the following `%s` errors:",
                    "RepoExitError",
                ),
                mock.call("foo\nbar\nbaz\nhello\nworld"),
                mock.call("+%d additional errors...", 1),
            ]
        )

    @mock.patch.object(RepoLogger, "error")
    def test_log_aggregated_errors_logs_single_error(self, mock_error):
        """Test if log_aggregated_errors logs empty aggregated_errors."""
        logger = RepoLogger(__name__)
        logger.log_aggregated_errors(RepoExitError())

        mock_error.assert_has_calls(
            [
                mock.call("=" * 80),
                mock.call("Repo command failed: %s", "RepoExitError"),
            ]
        )

    def test_log_with_format_string(self):
        """Test different log levels with format strings."""

        # Set color output to "always" for consistent test results.
        # This ensures the logger's behavior is uniform across different
        # environments and git configurations.
        SetDefaultColoring("always")

        # Regex pattern to match optional ANSI color codes.
        # \033    - Escape character
        # \[      - Opening square bracket
        # [0-9;]* - Zero or more digits or semicolons
        # m       - Ending 'm' character
        # ?       - Makes the entire group optional
        opt_color = r"(\033\[[0-9;]*m)?"

        for level in (logging.INFO, logging.WARN, logging.ERROR):
            name = logging.getLevelName(level)

            with self.subTest(level=level, name=name):
                output = io.StringIO()

                with contextlib.redirect_stderr(output):
                    logger = RepoLogger(__name__)
                    logger.log(level, "%s", "100% pass")

                self.assertRegex(
                    output.getvalue().strip(),
                    f"^{opt_color}100% pass{opt_color}$",
                    f"failed for level {name}",
                )


@pytest.mark.unit
class TestRepoLoggerInit(unittest.TestCase):
    """Tests for RepoLogger initialization."""

    def test_logger_inherits_from_logging_logger(self):
        """RepoLogger should inherit from logging.Logger."""
        logger = RepoLogger(__name__)
        self.assertIsInstance(logger, logging.Logger)

    def test_logger_adds_handler(self):
        """RepoLogger should add a handler on initialization."""
        logger = RepoLogger(__name__)
        self.assertGreater(len(logger.handlers), 0)

    def test_logger_uses_coloring_formatter(self):
        """RepoLogger should use _LogColoringFormatter."""
        from kanon_cli.repo.repo_logging import _LogColoringFormatter

        logger = RepoLogger(__name__)
        handler = logger.handlers[0]
        self.assertIsInstance(handler.formatter, _LogColoringFormatter)

    def test_logger_accepts_custom_config(self):
        """RepoLogger should accept custom config."""
        config = mock.Mock()
        config.GetString.return_value = None
        logger = RepoLogger(__name__, config=config)
        self.assertIsNotNone(logger)


@pytest.mark.unit
class TestLogColoringFormatter(unittest.TestCase):
    """Tests for _LogColoringFormatter."""

    def test_formatter_initializes_with_config(self):
        """_LogColoringFormatter should initialize with config."""
        from kanon_cli.repo.repo_logging import _LogColoringFormatter

        config = mock.Mock()
        config.GetString.return_value = None
        formatter = _LogColoringFormatter(config)
        self.assertIsNotNone(formatter.config)

    def test_formatter_uses_default_config_when_none(self):
        """_LogColoringFormatter should use default config when None."""
        from kanon_cli.repo.repo_logging import _LogColoringFormatter, _ConfigMock

        formatter = _LogColoringFormatter()
        self.assertIsInstance(formatter.config, _ConfigMock)

    def test_formatter_format_applies_color(self):
        """_LogColoringFormatter.format should apply color to message."""
        from kanon_cli.repo.repo_logging import _LogColoringFormatter

        SetDefaultColoring("always")
        formatter = _LogColoringFormatter()
        record = logging.LogRecord("test", logging.ERROR, "path", 1, "test message", (), None)
        result = formatter.format(record)
        # Should contain ANSI codes or message
        self.assertIn("test message", result)

    def test_formatter_format_returns_plain_for_info(self):
        """_LogColoringFormatter.format should return plain text for INFO."""
        from kanon_cli.repo.repo_logging import _LogColoringFormatter

        formatter = _LogColoringFormatter()
        record = logging.LogRecord("test", logging.INFO, "path", 1, "test message", (), None)
        result = formatter.format(record)
        self.assertIn("test message", result)


@pytest.mark.unit
class TestLogColoring(unittest.TestCase):
    """Tests for _LogColoring class."""

    def test_log_coloring_initializes(self):
        """_LogColoring should initialize correctly."""
        from kanon_cli.repo.repo_logging import _LogColoring, _ConfigMock

        config = _ConfigMock()
        coloring = _LogColoring(config)
        self.assertIsNotNone(coloring.error)
        self.assertIsNotNone(coloring.warning)

    def test_log_coloring_has_level_map(self):
        """_LogColoring should have levelMap with ERROR and WARNING."""
        from kanon_cli.repo.repo_logging import _LogColoring, _ConfigMock

        config = _ConfigMock()
        coloring = _LogColoring(config)
        self.assertIn("ERROR", coloring.levelMap)
        self.assertIn("WARNING", coloring.levelMap)

    def test_log_coloring_error_is_callable(self):
        """_LogColoring.error should be callable."""
        from kanon_cli.repo.repo_logging import _LogColoring, _ConfigMock

        config = _ConfigMock()
        coloring = _LogColoring(config)
        self.assertTrue(callable(coloring.error))

    def test_log_coloring_warning_is_callable(self):
        """_LogColoring.warning should be callable."""
        from kanon_cli.repo.repo_logging import _LogColoring, _ConfigMock

        config = _ConfigMock()
        coloring = _LogColoring(config)
        self.assertTrue(callable(coloring.warning))


@pytest.mark.unit
class TestConfigMock(unittest.TestCase):
    """Tests for _ConfigMock class."""

    def test_config_mock_has_default_values(self):
        """_ConfigMock should have default_values attribute."""
        from kanon_cli.repo.repo_logging import _ConfigMock

        config = _ConfigMock()
        self.assertIsInstance(config.default_values, dict)

    def test_config_mock_get_string_returns_value(self):
        """_ConfigMock.GetString should return value from defaults."""
        from kanon_cli.repo.repo_logging import _ConfigMock

        config = _ConfigMock()
        result = config.GetString("color.ui")
        self.assertEqual(result, "auto")

    def test_config_mock_get_string_returns_none_for_missing(self):
        """_ConfigMock.GetString should return None for missing keys."""
        from kanon_cli.repo.repo_logging import _ConfigMock

        config = _ConfigMock()
        result = config.GetString("nonexistent.key")
        self.assertIsNone(result)


@pytest.mark.unit
class TestLogAggregatedErrorsWithNoErrors(unittest.TestCase):
    """Tests for log_aggregated_errors with various scenarios."""

    @mock.patch.object(RepoLogger, "error")
    def test_log_aggregated_errors_with_none_list(self, mock_error):
        """log_aggregated_errors should handle None aggregate_errors."""
        logger = RepoLogger(__name__)
        logger.log_aggregated_errors(RepoExitError(aggregate_errors=None))
        # Should call error for separator and message
        self.assertGreater(mock_error.call_count, 0)

    @mock.patch.object(RepoLogger, "error")
    def test_log_aggregated_errors_with_empty_list(self, mock_error):
        """log_aggregated_errors should handle empty aggregate_errors."""
        logger = RepoLogger(__name__)
        logger.log_aggregated_errors(RepoExitError(aggregate_errors=[]))
        # Should call error for separator and single error message
        self.assertGreater(mock_error.call_count, 1)

    @mock.patch.object(RepoLogger, "error")
    def test_log_aggregated_errors_with_exactly_max_errors(self, mock_error):
        """log_aggregated_errors should not show +N when exactly MAX_PRINT_ERRORS."""
        from kanon_cli.repo.repo_logging import MAX_PRINT_ERRORS

        logger = RepoLogger(__name__)
        errors = [Exception(f"error{i}") for i in range(MAX_PRINT_ERRORS)]
        logger.log_aggregated_errors(RepoExitError(aggregate_errors=errors))
        # Should not call error with "+N additional" message
        calls = [str(call) for call in mock_error.call_args_list]
        additional_calls = [c for c in calls if "additional" in c]
        self.assertEqual(len(additional_calls), 0)

    @mock.patch.object(RepoLogger, "error")
    def test_log_aggregated_errors_with_one_extra_error(self, mock_error):
        """log_aggregated_errors should show +1 when one over MAX_PRINT_ERRORS."""
        from kanon_cli.repo.repo_logging import MAX_PRINT_ERRORS

        logger = RepoLogger(__name__)
        errors = [Exception(f"error{i}") for i in range(MAX_PRINT_ERRORS + 1)]
        logger.log_aggregated_errors(RepoExitError(aggregate_errors=errors))
        # Should call error with "+1 additional" message
        calls = [str(call) for call in mock_error.call_args_list]
        additional_calls = [c for c in calls if "+1 additional" in c or "call('+%d additional" in c]
        self.assertGreater(len(additional_calls), 0)
