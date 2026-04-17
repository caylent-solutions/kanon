# Copyright (C) 2024 The Android Open Source Project
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

"""Unittests for the progress.py module."""

import unittest
from unittest import mock

import pytest

from kanon_cli.repo import progress


@pytest.mark.unit
class TestConvertToHms(unittest.TestCase):
    """Tests for convert_to_hms()."""

    def test_zero_seconds(self):
        hours, mins, secs = progress.convert_to_hms(0)
        self.assertEqual(hours, 0)
        self.assertEqual(mins, 0)
        self.assertEqual(secs, 0)

    def test_fractional_seconds(self):
        hours, mins, secs = progress.convert_to_hms(0.5)
        self.assertEqual(hours, 0)
        self.assertEqual(mins, 0)
        self.assertAlmostEqual(secs, 0.5)

    def test_ninety_seconds(self):
        hours, mins, secs = progress.convert_to_hms(90)
        self.assertEqual(hours, 0)
        self.assertEqual(mins, 1)
        self.assertAlmostEqual(secs, 30.0)

    def test_exactly_one_hour(self):
        hours, mins, secs = progress.convert_to_hms(3600)
        self.assertEqual(hours, 1)
        self.assertEqual(mins, 0)
        self.assertAlmostEqual(secs, 0.0)

    def test_mixed_hours_minutes_seconds(self):
        hours, mins, secs = progress.convert_to_hms(3661)
        self.assertEqual(hours, 1)
        self.assertEqual(mins, 1)
        self.assertAlmostEqual(secs, 1.0)

    def test_large_value(self):
        hours, mins, secs = progress.convert_to_hms(7325.5)
        self.assertEqual(hours, 2)
        self.assertEqual(mins, 2)
        self.assertAlmostEqual(secs, 5.5)

    def test_returns_int_hours_and_mins(self):
        hours, mins, secs = progress.convert_to_hms(3661.123)
        self.assertIsInstance(hours, int)
        self.assertIsInstance(mins, int)
        self.assertIsInstance(secs, float)


@pytest.mark.unit
class TestDurationStr(unittest.TestCase):
    """Tests for duration_str()."""

    def test_zero(self):
        self.assertEqual(progress.duration_str(0), "0.000s")

    def test_seconds_only(self):
        self.assertEqual(progress.duration_str(5.123), "5.123s")

    def test_minutes_and_seconds(self):
        self.assertEqual(progress.duration_str(90), "1m30.000s")

    def test_hours_minutes_seconds(self):
        self.assertEqual(progress.duration_str(3661), "1h1m1.000s")

    def test_no_minutes_prefix_when_zero_minutes(self):
        result = progress.duration_str(5)
        self.assertNotIn("m", result.replace("s", "").split(".")[0])

    def test_no_hours_prefix_when_zero_hours(self):
        result = progress.duration_str(90)
        self.assertNotIn("h", result)

    def test_fractional_seconds_precision(self):
        result = progress.duration_str(1.5)
        self.assertEqual(result, "1.500s")


@pytest.mark.unit
class TestElapsedStr(unittest.TestCase):
    """Tests for elapsed_str()."""

    def test_zero(self):
        self.assertEqual(progress.elapsed_str(0), "0:00")

    def test_under_one_minute(self):
        self.assertEqual(progress.elapsed_str(45), "0:45")

    def test_one_minute(self):
        self.assertEqual(progress.elapsed_str(60), "1:00")

    def test_under_ten_minutes_no_leading_zero(self):
        result = progress.elapsed_str(90)
        self.assertEqual(result, "1:30")

    def test_over_ten_minutes(self):
        result = progress.elapsed_str(605)
        self.assertEqual(result, "10:05")

    def test_one_hour(self):
        result = progress.elapsed_str(3600)
        self.assertEqual(result, "1:00:00")

    def test_hours_with_leading_zero_minutes(self):
        result = progress.elapsed_str(3661)
        self.assertEqual(result, "1:01:01")

    def test_large_hours(self):
        result = progress.elapsed_str(36000)
        self.assertEqual(result, "10:00:00")


@pytest.mark.unit
class TestJobsStr(unittest.TestCase):
    """Tests for jobs_str()."""

    def test_singular(self):
        self.assertEqual(progress.jobs_str(1), "1 job")

    def test_plural(self):
        self.assertEqual(progress.jobs_str(3), "3 jobs")

    def test_zero(self):
        self.assertEqual(progress.jobs_str(0), "0 job")

    def test_two(self):
        self.assertEqual(progress.jobs_str(2), "2 jobs")


@pytest.mark.unit
class TestProgressInit(unittest.TestCase):
    """Tests for Progress.__init__()."""

    @mock.patch.object(progress, "_TTY", False)
    def test_default_values(self):
        p = progress.Progress("Syncing", total=10, quiet=True)
        self.assertEqual(p._title, "Syncing")
        self.assertEqual(p._total, 10)
        self.assertEqual(p._done, 0)
        self.assertFalse(p._show_jobs)
        self.assertEqual(p._active, 0)
        self.assertFalse(p._ended)
        self.assertEqual(p._units, "")
        self.assertFalse(p._quiet is False)

    @mock.patch.object(progress, "_TTY", False)
    def test_delay_true_means_not_shown(self):
        p = progress.Progress("Test", total=5, delay=True, quiet=True)
        self.assertFalse(p._show)

    @mock.patch.object(progress, "_TTY", False)
    def test_delay_false_means_shown(self):
        p = progress.Progress("Test", total=5, delay=False, quiet=True)
        self.assertTrue(p._show)

    @mock.patch.object(progress, "_TTY", False)
    def test_units_stored(self):
        p = progress.Progress("Test", total=5, units=" kB", quiet=True)
        self.assertEqual(p._units, " kB")

    @mock.patch.object(progress, "_TTY", False)
    def test_quiet_flag(self):
        p = progress.Progress("Test", total=5, quiet=True)
        self.assertTrue(p._quiet)

    @mock.patch.object(progress, "_TTY", True)
    def test_elide_true_with_tty(self):
        p = progress.Progress("Test", total=5, elide=True, quiet=True)
        self.assertTrue(p._elide)

    @mock.patch.object(progress, "_TTY", False)
    def test_elide_true_without_tty(self):
        p = progress.Progress("Test", total=5, elide=True, quiet=True)
        self.assertFalse(p._elide)


@pytest.mark.unit
class TestProgressUpdateNoTty(unittest.TestCase):
    """Tests that update returns early when not a TTY."""

    @mock.patch.object(progress, "_TTY", False)
    @mock.patch("sys.stderr")
    def test_update_does_not_write_when_no_tty(self, mock_stderr):
        p = progress.Progress("Test", total=5, delay=False, quiet=False)
        p.update(inc=1, msg="working")
        mock_stderr.write.assert_not_called()

    @mock.patch.object(progress, "_TTY", False)
    def test_update_still_increments_done_when_no_tty(self):
        p = progress.Progress("Test", total=5, delay=False, quiet=True)
        p.update(inc=1, msg="working")
        self.assertEqual(p._done, 1)


@pytest.mark.unit
class TestProgressUpdateIncrementsDone(unittest.TestCase):
    """Tests that update increments the done counter."""

    @mock.patch.object(progress, "_TTY", False)
    def test_single_increment(self):
        p = progress.Progress("Test", total=10, quiet=True)
        p.update(inc=1)
        self.assertEqual(p._done, 1)

    @mock.patch.object(progress, "_TTY", False)
    def test_multiple_increments(self):
        p = progress.Progress("Test", total=10, quiet=True)
        p.update(inc=3)
        p.update(inc=2)
        self.assertEqual(p._done, 5)

    @mock.patch.object(progress, "_TTY", False)
    def test_zero_increment(self):
        p = progress.Progress("Test", total=10, quiet=True)
        p.update(inc=0)
        self.assertEqual(p._done, 0)

    @mock.patch.object(progress, "_TTY", False)
    def test_last_msg_updated(self):
        p = progress.Progress("Test", total=10, quiet=True)
        p.update(inc=1, msg="first")
        self.assertEqual(p._last_msg, "first")
        p.update(inc=1, msg="second")
        self.assertEqual(p._last_msg, "second")

    @mock.patch.object(progress, "_TTY", False)
    def test_none_msg_preserves_last(self):
        p = progress.Progress("Test", total=10, quiet=True)
        p.update(inc=1, msg="keep this")
        p.update(inc=1, msg=None)
        self.assertEqual(p._last_msg, "keep this")


@pytest.mark.unit
class TestProgressEnd(unittest.TestCase):
    """Tests for Progress.end()."""

    @mock.patch.object(progress, "_TTY", False)
    def test_end_sets_ended(self):
        p = progress.Progress("Test", total=5, quiet=True)
        self.assertFalse(p._ended)
        p.end()
        self.assertTrue(p._ended)

    @mock.patch.object(progress, "_TTY", False)
    def test_double_end_is_noop(self):
        p = progress.Progress("Test", total=5, quiet=True)
        p.end()
        self.assertTrue(p._ended)
        # Calling end() again should not raise.
        p.end()
        self.assertTrue(p._ended)

    @mock.patch.object(progress, "_TTY", False)
    def test_end_sets_update_event(self):
        p = progress.Progress("Test", total=5, quiet=True)
        self.assertFalse(p._update_event.is_set())
        p.end()
        self.assertTrue(p._update_event.is_set())


@pytest.mark.unit
class TestProgressStartAndFinish(unittest.TestCase):
    """Tests for Progress.start() and Progress.finish()."""

    @mock.patch.object(progress, "_TTY", False)
    def test_start_increments_active(self):
        p = progress.Progress("Test", total=5, quiet=True)
        self.assertEqual(p._active, 0)
        p.start("task_a")
        self.assertEqual(p._active, 1)

    @mock.patch.object(progress, "_TTY", False)
    def test_finish_decrements_active(self):
        p = progress.Progress("Test", total=5, quiet=True)
        p.start("task_a")
        self.assertEqual(p._active, 1)
        p.finish("task_a")
        self.assertEqual(p._active, 0)

    @mock.patch.object(progress, "_TTY", False)
    def test_start_finish_multiple(self):
        p = progress.Progress("Test", total=5, quiet=True)
        p.start("task_a")
        p.start("task_b")
        self.assertEqual(p._active, 2)
        p.finish("task_a")
        self.assertEqual(p._active, 1)
        p.finish("task_b")
        self.assertEqual(p._active, 0)

    @mock.patch.object(progress, "_TTY", False)
    def test_start_updates_done_via_update(self):
        p = progress.Progress("Test", total=5, quiet=True)
        initial_done = p._done
        p.start("task_a")
        # start calls update(inc=0), so done should not change.
        self.assertEqual(p._done, initial_done)

    @mock.patch.object(progress, "_TTY", False)
    def test_finish_increments_done(self):
        p = progress.Progress("Test", total=5, quiet=True)
        p.start("task_a")
        p.finish("task_a")
        # finish calls update(inc=1 by default), so done increments.
        self.assertEqual(p._done, 1)


@pytest.mark.unit
class TestProgressShowJobsWhenParallel(unittest.TestCase):
    """Tests that _show_jobs is set to True when _active > 1."""

    @mock.patch.object(progress, "_TTY", False)
    def test_single_job_does_not_set_show_jobs(self):
        p = progress.Progress("Test", total=5, quiet=True)
        p.start("task_a")
        self.assertFalse(p._show_jobs)

    @mock.patch.object(progress, "_TTY", False)
    def test_two_concurrent_jobs_sets_show_jobs(self):
        p = progress.Progress("Test", total=5, quiet=True)
        p.start("task_a")
        p.start("task_b")
        self.assertTrue(p._show_jobs)

    @mock.patch.object(progress, "_TTY", False)
    def test_show_jobs_stays_true_after_finish(self):
        p = progress.Progress("Test", total=5, quiet=True)
        p.start("task_a")
        p.start("task_b")
        self.assertTrue(p._show_jobs)
        p.finish("task_a")
        p.finish("task_b")
        # Once set, _show_jobs should remain True.
        self.assertTrue(p._show_jobs)

    @mock.patch.object(progress, "_TTY", False)
    def test_show_jobs_false_initially(self):
        p = progress.Progress("Test", total=5, quiet=True)
        self.assertFalse(p._show_jobs)


@pytest.mark.unit
class TestProgressDisplayMessage(unittest.TestCase):
    """Tests for Progress.display_message()."""

    @mock.patch.object(progress, "_TTY", True)
    @mock.patch("sys.stderr")
    def test_display_message_writes_message(self, mock_stderr):
        """display_message should write message to stderr."""
        with mock.patch("kanon_cli.repo.progress.IsTraceToStderr", return_value=False):
            p = progress.Progress("Test", total=5, delay=False, quiet=False)
            p.display_message("test message")
            # Should write the message
            calls = [str(call) for call in mock_stderr.write.call_args_list]
            self.assertTrue(any("test message" in call for call in calls))

    @mock.patch.object(progress, "_TTY", False)
    @mock.patch("sys.stderr")
    def test_display_message_returns_early_no_tty(self, mock_stderr):
        """display_message should return early when not TTY."""
        p = progress.Progress("Test", total=5, delay=False, quiet=False)
        p.display_message("test message")
        # Should not write when not TTY
        mock_stderr.write.assert_not_called()

    @mock.patch.object(progress, "_TTY", True)
    @mock.patch("sys.stderr")
    def test_display_message_returns_early_when_quiet(self, mock_stderr):
        """display_message should return early when quiet."""
        with mock.patch("kanon_cli.repo.progress.IsTraceToStderr", return_value=False):
            p = progress.Progress("Test", total=5, delay=False, quiet=True)
            p.display_message("test message")
            mock_stderr.write.assert_not_called()


@pytest.mark.unit
class TestProgressWrite(unittest.TestCase):
    """Tests for Progress._write() method."""

    @mock.patch.object(progress, "_TTY", True)
    @mock.patch("sys.stderr")
    def test_write_prepends_carriage_return(self, mock_stderr):
        """_write should prepend carriage return to output."""
        with mock.patch("kanon_cli.repo.progress.IsTraceToStderr", return_value=False):
            with mock.patch("os.get_terminal_size", return_value=mock.Mock(columns=80)):
                p = progress.Progress("Test", total=5, delay=False, quiet=False, elide=True)
                p._write("test content")
                call_args = mock_stderr.write.call_args[0][0]
                self.assertTrue(call_args.startswith("\r"))

    @mock.patch.object(progress, "_TTY", True)
    @mock.patch("sys.stderr")
    def test_write_elides_long_content(self, mock_stderr):
        """_write should elide content longer than terminal width."""
        with mock.patch("kanon_cli.repo.progress.IsTraceToStderr", return_value=False):
            mock_size = mock.Mock()
            mock_size.columns = 20
            with mock.patch("os.get_terminal_size", return_value=mock_size):
                p = progress.Progress("Test", total=5, delay=False, quiet=False, elide=True)
                p._write("x" * 100)
                call_args = mock_stderr.write.call_args[0][0]
                self.assertTrue(len(call_args) <= 21)  # 20 + newline
                self.assertTrue(call_args.endswith(".."))

    @mock.patch.object(progress, "_TTY", True)
    @mock.patch("sys.stderr")
    def test_write_calls_flush(self, mock_stderr):
        """_write should flush stderr after writing."""
        with mock.patch("kanon_cli.repo.progress.IsTraceToStderr", return_value=False):
            with mock.patch("os.get_terminal_size", return_value=mock.Mock(columns=80)):
                p = progress.Progress("Test", total=5, delay=False, quiet=False, elide=True)
                p._write("test")
                mock_stderr.flush.assert_called_once()


@pytest.mark.unit
class TestProgressUpdateWithTotal(unittest.TestCase):
    """Tests for Progress.update() with total set."""

    @mock.patch.object(progress, "_TTY", True)
    @mock.patch("sys.stderr")
    def test_update_shows_percentage(self, mock_stderr):
        """update should show percentage when total is set."""
        with mock.patch("kanon_cli.repo.progress.IsTraceToStderr", return_value=False):
            with mock.patch("os.get_terminal_size", return_value=mock.Mock(columns=100)):
                p = progress.Progress("Test", total=10, delay=False, quiet=False, elide=True)
                p.update(inc=5)
                call_args = mock_stderr.write.call_args[0][0]
                self.assertIn("50%", call_args)

    @mock.patch.object(progress, "_TTY", True)
    @mock.patch("sys.stderr")
    def test_update_shows_elapsed_time(self, mock_stderr):
        """update should show elapsed time when show_elapsed is True."""
        with mock.patch("kanon_cli.repo.progress.IsTraceToStderr", return_value=False):
            mock_size = mock.Mock()
            mock_size.columns = 100
            with mock.patch("os.get_terminal_size", return_value=mock_size):
                # Provide enough time values for init and update
                with mock.patch("time.time", side_effect=[0, 0, 10]):
                    p = progress.Progress(
                        "Test",
                        total=10,
                        delay=False,
                        quiet=False,
                        show_elapsed=True,
                        elide=True,
                    )
                    p.update(inc=5)
                    call_args = mock_stderr.write.call_args[0][0]
                    # Should contain time format
                    self.assertIn("0:", call_args)

    @mock.patch.object(progress, "_TTY", True)
    @mock.patch("sys.stderr")
    def test_update_shows_jobs_when_active(self, mock_stderr):
        """update should show job count when _show_jobs is True."""
        with mock.patch("kanon_cli.repo.progress.IsTraceToStderr", return_value=False):
            with mock.patch("os.get_terminal_size", return_value=mock.Mock(columns=100)):
                p = progress.Progress("Test", total=10, delay=False, quiet=False, elide=True)
                p.start("job1")
                p.start("job2")
                p.update(inc=5)
                call_args = mock_stderr.write.call_args[0][0]
                self.assertIn("job", call_args)


@pytest.mark.unit
class TestProgressUpdateWithoutTotal(unittest.TestCase):
    """Tests for Progress.update() without total set."""

    @mock.patch.object(progress, "_TTY", True)
    @mock.patch("sys.stderr")
    def test_update_shows_count_without_total(self, mock_stderr):
        """update should show count when total is 0."""
        with mock.patch("kanon_cli.repo.progress.IsTraceToStderr", return_value=False):
            with mock.patch("os.get_terminal_size", return_value=mock.Mock(columns=100)):
                p = progress.Progress("Test", total=0, delay=False, quiet=False, elide=True)
                p.update(inc=1)
                p.update(inc=1)
                call_args = mock_stderr.write.call_args[0][0]
                self.assertIn("2", call_args)


@pytest.mark.unit
class TestProgressUpdateDelay(unittest.TestCase):
    """Tests for Progress.update() delay logic."""

    @mock.patch.object(progress, "_TTY", True)
    @mock.patch("sys.stderr")
    def test_update_respects_delay(self, mock_stderr):
        """update should not display until delay passes."""
        with mock.patch("kanon_cli.repo.progress.IsTraceToStderr", return_value=False):
            with mock.patch("time.time", side_effect=[0, 0.3, 0.6]):
                p = progress.Progress("Test", total=10, delay=True, quiet=False)
                p.update(inc=1)
                mock_stderr.write.assert_not_called()
                p.update(inc=1)
                mock_stderr.write.assert_called()

    @mock.patch.object(progress, "_TTY", True)
    @mock.patch("sys.stderr")
    def test_update_shows_immediately_when_no_delay(self, mock_stderr):
        """update should display immediately when delay=False."""
        with mock.patch("kanon_cli.repo.progress.IsTraceToStderr", return_value=False):
            with mock.patch("os.get_terminal_size", return_value=mock.Mock(columns=100)):
                p = progress.Progress("Test", total=10, delay=False, quiet=False, elide=True)
                p.update(inc=1)
                mock_stderr.write.assert_called()


@pytest.mark.unit
class TestProgressUpdateLoop(unittest.TestCase):
    """Tests for Progress._update_loop() method."""

    @mock.patch.object(progress, "_TTY", False)
    def test_update_loop_exits_on_event(self):
        """_update_loop should exit when _update_event is set."""
        p = progress.Progress("Test", total=5, delay=False, quiet=True)
        p._update_event.set()
        # The loop should exit immediately
        with mock.patch.object(p, "update") as mock_update:
            p._update_loop()
            # Should call update at least once before checking event
            self.assertGreaterEqual(mock_update.call_count, 1)
