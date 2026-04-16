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

"""Unittests for the color.py module."""

import os
import unittest
from unittest import mock

import pytest

import color
import git_config


def fixture(*paths):
    """Return a path relative to test/fixtures."""
    return os.path.join(os.path.dirname(__file__), "fixtures", *paths)


class ColoringTests(unittest.TestCase):
    """tests of the Coloring class."""

    def setUp(self):
        """Create a GitConfig object using the test.gitconfig fixture."""
        config_fixture = fixture("test.gitconfig")
        self.config = git_config.GitConfig(config_fixture)
        color.SetDefaultColoring("true")
        self.color = color.Coloring(self.config, "status")

    def tearDown(self):
        """Reset default coloring to None."""
        color.SetDefaultColoring(None)

    def test_Color_Parse_all_params_none(self):
        """all params are None"""
        val = self.color._parse(None, None, None, None)
        self.assertEqual("", val)

    def test_Color_Parse_first_parameter_none(self):
        """check fg & bg & attr"""
        val = self.color._parse(None, "black", "red", "ul")
        self.assertEqual("\x1b[4;30;41m", val)

    def test_Color_Parse_one_entry(self):
        """check fg"""
        val = self.color._parse("one", None, None, None)
        self.assertEqual("\033[33m", val)

    def test_Color_Parse_two_entry(self):
        """check fg & bg"""
        val = self.color._parse("two", None, None, None)
        self.assertEqual("\033[35;46m", val)

    def test_Color_Parse_three_entry(self):
        """check fg & bg & attr"""
        val = self.color._parse("three", None, None, None)
        self.assertEqual("\033[4;30;41m", val)

    def test_Color_Parse_reset_entry(self):
        """check reset entry"""
        val = self.color._parse("reset", None, None, None)
        self.assertEqual("\033[m", val)

    def test_Color_Parse_empty_entry(self):
        """check empty entry"""
        val = self.color._parse("none", "blue", "white", "dim")
        self.assertEqual("\033[2;34;47m", val)
        val = self.color._parse("empty", "green", "white", "bold")
        self.assertEqual("\033[1;32;47m", val)


@pytest.mark.unit
class ColorFunctionTests(unittest.TestCase):
    """Tests for color module functions."""

    def test_is_color_valid_colors(self):
        """is_color should return True for valid colors."""
        self.assertTrue(color.is_color("red"))
        self.assertTrue(color.is_color("green"))
        self.assertTrue(color.is_color("blue"))
        self.assertTrue(color.is_color("black"))
        self.assertTrue(color.is_color("white"))
        self.assertTrue(color.is_color("cyan"))
        self.assertTrue(color.is_color("magenta"))
        self.assertTrue(color.is_color("yellow"))
        self.assertTrue(color.is_color("normal"))
        self.assertTrue(color.is_color(None))

    def test_is_color_invalid_colors(self):
        """is_color should return False for invalid colors."""
        self.assertFalse(color.is_color("purple"))
        self.assertFalse(color.is_color("orange"))
        self.assertFalse(color.is_color("invalid"))

    def test_is_attr_valid_attrs(self):
        """is_attr should return True for valid attributes."""
        self.assertTrue(color.is_attr("bold"))
        self.assertTrue(color.is_attr("dim"))
        self.assertTrue(color.is_attr("ul"))
        self.assertTrue(color.is_attr("blink"))
        self.assertTrue(color.is_attr("reverse"))
        self.assertTrue(color.is_attr(None))

    def test_is_attr_invalid_attrs(self):
        """is_attr should return False for invalid attributes."""
        self.assertFalse(color.is_attr("italic"))
        self.assertFalse(color.is_attr("underline"))
        self.assertFalse(color.is_attr("invalid"))


@pytest.mark.unit
class ColorHelperTests(unittest.TestCase):
    """Tests for _Color helper function."""

    def test_color_only_fg(self):
        """_Color should generate code for foreground only."""
        result = color._Color(fg="red", bg=None, attr=None)
        self.assertEqual(result, "\033[31m")

    def test_color_only_bg(self):
        """_Color should generate code for background only."""
        result = color._Color(fg=None, bg="blue", attr=None)
        self.assertEqual(result, "\033[44m")

    def test_color_only_attr(self):
        """_Color should generate code for attribute only."""
        result = color._Color(fg=None, bg=None, attr="bold")
        self.assertEqual(result, "\033[1m")

    def test_color_fg_and_bg(self):
        """_Color should generate code for fg and bg."""
        result = color._Color(fg="green", bg="white", attr=None)
        self.assertEqual(result, "\033[32;47m")

    def test_color_all_params(self):
        """_Color should generate code for all params."""
        result = color._Color(fg="yellow", bg="black", attr="ul")
        self.assertEqual(result, "\033[4;33;40m")

    def test_color_all_none_returns_empty(self):
        """_Color with all None should return empty string."""
        result = color._Color(fg=None, bg=None, attr=None)
        self.assertEqual(result, "")

    def test_color_high_color_fg(self):
        """_Color should handle high color numbers for fg."""
        result = color._Color(fg="red", bg=None, attr=None)
        self.assertIn("31", result)

    def test_color_high_color_bg(self):
        """_Color should handle high color numbers for bg."""
        result = color._Color(fg=None, bg="cyan", attr=None)
        self.assertIn("46", result)


@pytest.mark.unit
class SetDefaultColoringTests(unittest.TestCase):
    """Tests for SetDefaultColoring function."""

    def setUp(self):
        """Save and clear default coloring before each test."""
        self.original_default = color.DEFAULT

    def tearDown(self):
        """Restore default coloring after each test."""
        color.DEFAULT = self.original_default

    def test_set_to_auto(self):
        """SetDefaultColoring('auto') should set DEFAULT to 'auto'."""
        color.SetDefaultColoring("auto")
        self.assertEqual(color.DEFAULT, "auto")

    def test_set_to_always(self):
        """SetDefaultColoring('always') should set DEFAULT to 'always'."""
        color.SetDefaultColoring("always")
        self.assertEqual(color.DEFAULT, "always")

    def test_set_to_yes(self):
        """SetDefaultColoring('yes') should set DEFAULT to 'always'."""
        color.SetDefaultColoring("yes")
        self.assertEqual(color.DEFAULT, "always")

    def test_set_to_true(self):
        """SetDefaultColoring('true') should set DEFAULT to 'always'."""
        color.SetDefaultColoring("true")
        self.assertEqual(color.DEFAULT, "always")

    def test_set_to_true_string(self):
        """SetDefaultColoring('true') should set DEFAULT to 'always'."""
        color.SetDefaultColoring("true")
        self.assertEqual(color.DEFAULT, "always")

    def test_set_to_never(self):
        """SetDefaultColoring('never') should set DEFAULT to 'never'."""
        color.SetDefaultColoring("never")
        self.assertEqual(color.DEFAULT, "never")

    def test_set_to_no(self):
        """SetDefaultColoring('no') should set DEFAULT to 'never'."""
        color.SetDefaultColoring("no")
        self.assertEqual(color.DEFAULT, "never")

    def test_set_to_false_string(self):
        """SetDefaultColoring('false') should set DEFAULT to 'never'."""
        color.SetDefaultColoring("false")
        self.assertEqual(color.DEFAULT, "never")

    def test_set_to_none_does_nothing(self):
        """SetDefaultColoring(None) should not change DEFAULT."""
        color.DEFAULT = "test_value"
        color.SetDefaultColoring(None)
        self.assertEqual(color.DEFAULT, "test_value")

    def test_case_insensitive(self):
        """SetDefaultColoring should be case-insensitive."""
        color.SetDefaultColoring("ALWAYS")
        self.assertEqual(color.DEFAULT, "always")
        color.SetDefaultColoring("Never")
        self.assertEqual(color.DEFAULT, "never")


@pytest.mark.unit
class ColoringInitTests(unittest.TestCase):
    """Tests for Coloring.__init__."""

    def setUp(self):
        self._saved_default = color.DEFAULT

    def tearDown(self):
        color.DEFAULT = self._saved_default

    def test_init_with_default_none(self):
        """Coloring should read from config when DEFAULT is None."""
        config = unittest.mock.MagicMock()
        config.GetString.return_value = "always"
        color.DEFAULT = None
        with mock.patch("os.isatty", return_value=True):
            coloring = color.Coloring(config, "test")
            self.assertTrue(coloring._on)

    def test_init_with_default_auto_and_tty(self):
        """Coloring with DEFAULT='auto' and TTY should enable colors."""
        config = unittest.mock.MagicMock()
        color.DEFAULT = "auto"
        with mock.patch("os.isatty", return_value=True):
            with mock.patch("pager.active", False):
                coloring = color.Coloring(config, "test")
                self.assertTrue(coloring._on)

    def test_init_with_default_auto_and_no_tty(self):
        """Coloring with DEFAULT='auto' and no TTY should disable colors."""
        config = unittest.mock.MagicMock()
        color.DEFAULT = "auto"
        with mock.patch("os.isatty", return_value=False):
            with mock.patch("pager.active", False):
                coloring = color.Coloring(config, "test")
                self.assertFalse(coloring._on)

    def test_init_with_default_always(self):
        """Coloring with DEFAULT='always' should always enable colors."""
        config = unittest.mock.MagicMock()
        color.DEFAULT = "always"
        coloring = color.Coloring(config, "test")
        self.assertTrue(coloring._on)

    def test_init_with_pager_active(self):
        """Coloring should enable when pager is active."""
        config = unittest.mock.MagicMock()
        color.DEFAULT = "auto"
        with mock.patch("os.isatty", return_value=False):
            with mock.patch("pager.active", True):
                coloring = color.Coloring(config, "test")
                self.assertTrue(coloring._on)

    def test_init_reads_color_ui_config(self):
        """Coloring should read color.ui config when section config is None."""
        config = unittest.mock.MagicMock()
        config.GetString.side_effect = lambda key: {
            "color.test": None,
            "color.ui": "always",
        }.get(key)
        color.DEFAULT = None
        coloring = color.Coloring(config, "test")
        self.assertTrue(coloring._on)


@pytest.mark.unit
class ColoringMethodTests(unittest.TestCase):
    """Tests for Coloring methods."""

    def setUp(self):
        """Create a Coloring instance for testing."""
        self._saved_default = color.DEFAULT
        config = unittest.mock.MagicMock()
        config.GetString.return_value = None
        color.SetDefaultColoring("always")
        self.coloring = color.Coloring(config, "test")

    def tearDown(self):
        color.DEFAULT = self._saved_default

    def test_redirect_changes_output(self):
        """redirect() should change the output stream."""
        new_out = unittest.mock.MagicMock()
        self.coloring.redirect(new_out)
        self.assertIs(self.coloring._out, new_out)

    def test_is_on_property(self):
        """is_on property should return _on value."""
        self.coloring._on = True
        self.assertTrue(self.coloring.is_on)
        self.coloring._on = False
        self.assertFalse(self.coloring.is_on)

    def test_write_formats_and_writes(self):
        """write() should format and write to output."""
        self.coloring._out = unittest.mock.MagicMock()
        self.coloring.write("test %s %d", "string", 42)
        self.coloring._out.write.assert_called_once_with("test string 42")

    def test_flush_calls_output_flush(self):
        """flush() should call flush on output stream."""
        self.coloring._out = unittest.mock.MagicMock()
        self.coloring.flush()
        self.coloring._out.flush.assert_called_once()

    def test_nl_writes_newline(self):
        """nl() should write a newline."""
        self.coloring._out = unittest.mock.MagicMock()
        self.coloring.nl()
        self.coloring._out.write.assert_called_once_with("\n")

    def test_printer_returns_callable(self):
        """printer() should return a callable function."""
        printer = self.coloring.printer(fg="red")
        self.assertTrue(callable(printer))

    def test_printer_output_includes_color_codes(self):
        """printer() output should include color codes when on."""
        self.coloring._on = True
        self.coloring._out = unittest.mock.MagicMock()
        printer = self.coloring.printer(fg="red")
        printer("test")
        call_args = self.coloring._out.write.call_args[0][0]
        self.assertIn("\033[", call_args)
        self.assertIn("test", call_args)

    def test_printer_formats_args(self):
        """printer() should format arguments."""
        self.coloring._out = unittest.mock.MagicMock()
        printer = self.coloring.printer(fg="green")
        printer("value: %d", 123)
        call_args = self.coloring._out.write.call_args[0][0]
        self.assertIn("value: 123", call_args)

    def test_nofmt_printer_returns_callable(self):
        """nofmt_printer() should return a callable function."""
        printer = self.coloring.nofmt_printer(fg="blue")
        self.assertTrue(callable(printer))

    def test_nofmt_printer_no_formatting(self):
        """nofmt_printer() should not format arguments."""
        self.coloring._out = unittest.mock.MagicMock()
        printer = self.coloring.nofmt_printer(fg="yellow")
        printer("value: %d")
        call_args = self.coloring._out.write.call_args[0][0]
        self.assertIn("value: %d", call_args)

    def test_colorer_returns_callable(self):
        """colorer() should return a callable function."""
        colorer_func = self.coloring.colorer(fg="cyan")
        self.assertTrue(callable(colorer_func))

    def test_colorer_returns_colored_string(self):
        """colorer() should return a colored string."""
        self.coloring._on = True
        colorer_func = self.coloring.colorer(fg="red")
        result = colorer_func("test")
        self.assertIn("\033[", result)
        self.assertIn("test", result)
        self.assertIn(color.RESET, result)

    def test_colorer_when_off_returns_plain_string(self):
        """colorer() when off should return plain string."""
        self.coloring._on = False
        colorer_func = self.coloring.colorer(fg="red")
        result = colorer_func("test")
        self.assertEqual(result, "test")

    def test_nofmt_colorer_returns_callable(self):
        """nofmt_colorer() should return a callable function."""
        colorer_func = self.coloring.nofmt_colorer(fg="magenta")
        self.assertTrue(callable(colorer_func))

    def test_nofmt_colorer_no_format(self):
        """nofmt_colorer() should not format the string."""
        self.coloring._on = True
        colorer_func = self.coloring.nofmt_colorer(fg="green")
        result = colorer_func("test %d %s")
        self.assertIn("test %d %s", result)

    def test_parse_reads_config(self):
        """_parse() should read configuration."""
        config = unittest.mock.MagicMock()
        config.GetString.return_value = "red"
        color.SetDefaultColoring("always")
        coloring = color.Coloring(config, "test")
        coloring._parse("myopt", None, None, None)
        config.GetString.assert_called()


@pytest.mark.unit
class ColoringParseComplexTests(unittest.TestCase):
    """Tests for Coloring._parse with complex inputs."""

    def setUp(self):
        """Create test config and coloring."""
        self._saved_default = color.DEFAULT
        self.config = unittest.mock.MagicMock()
        color.SetDefaultColoring("always")

    def tearDown(self):
        color.DEFAULT = self._saved_default

    def test_parse_handles_reset(self):
        """_parse should return RESET for 'reset' value."""
        self.config.GetString.return_value = "reset"
        coloring = color.Coloring(self.config, "test")
        result = coloring._parse("opt", None, None, None)
        self.assertEqual(result, color.RESET)

    def test_parse_handles_empty_string(self):
        """_parse should use defaults for empty string."""
        self.config.GetString.return_value = ""
        coloring = color.Coloring(self.config, "test")
        result = coloring._parse("opt", "red", "white", "bold")
        self.assertIn("31", result)  # red fg
        self.assertIn("47", result)  # white bg
        self.assertIn("1", result)  # bold

    def test_parse_with_multiple_colors_in_config(self):
        """_parse should handle multiple space-separated values."""
        self.config.GetString.return_value = "red blue"
        coloring = color.Coloring(self.config, "test")
        result = coloring._parse("opt", None, None, None)
        # First color is fg, second is bg
        self.assertIn("31", result)  # red fg
        self.assertIn("44", result)  # blue bg
