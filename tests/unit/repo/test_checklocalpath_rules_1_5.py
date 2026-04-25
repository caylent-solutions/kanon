"""Unit tests for _CheckLocalPath rules 1-5.

Covers:
  PATH-001  empty path is rejected
  PATH-002  tilde in path is rejected
  PATH-003  bad Unicode codepoint is rejected
  PATH-004  newline (or carriage-return) in path is rejected
  PATH-005  bare dot component is rejected when cwd_dot_ok is False
"""

import pytest

from kanon_cli.repo import manifest_xml


# Convenience alias -- keeps every call-site short.
_check = manifest_xml.XmlManifest._CheckLocalPath


# ---------------------------------------------------------------------------
# PATH-001  empty path
# ---------------------------------------------------------------------------


class TestPath001EmptyPath:
    """PATH-001: _CheckLocalPath rejects an empty string immediately.

    The function must return a non-None error message whose text
    matches 'empty paths not allowed' so callers can surface a clear
    diagnostic.
    """

    def test_empty_string_returns_error(self):
        """Empty string produces the canonical 'empty paths not allowed' message."""
        result = _check("")
        assert result is not None, "empty path must be rejected"
        assert result == "empty paths not allowed", f"expected 'empty paths not allowed', got {result!r}"

    def test_empty_string_rejected_regardless_of_flags(self):
        """Empty string is rejected even when all permissive flags are True."""
        result = _check("", dir_ok=True, cwd_dot_ok=True, abs_ok=True)
        assert result is not None, "empty path must be rejected even with all flags enabled"
        assert result == "empty paths not allowed"


# ---------------------------------------------------------------------------
# PATH-002  tilde in path
# ---------------------------------------------------------------------------


_TILDE_CASES = [
    "~",
    "~/foo",
    "foo~bar",
    "a/b/c~d/e",
    "~root",
]


class TestPath002TildeInPath:
    """PATH-002: _CheckLocalPath rejects any path containing a tilde.

    Windows 8.3 short-name expansion can turn '~' into unexpected paths.
    Any path containing this character must be rejected.
    """

    @pytest.mark.parametrize("path", _TILDE_CASES)
    def test_tilde_path_rejected(self, path):
        """Every path containing ~ must produce a non-None error."""
        result = _check(path)
        assert result is not None, f"path containing '~' must be rejected: {path!r}"

    @pytest.mark.parametrize("path", _TILDE_CASES)
    def test_tilde_error_message_mentions_tilde(self, path):
        """The error message must mention '~' so the user knows the exact cause."""
        result = _check(path)
        assert result is not None
        assert "~" in result, f"error message for {path!r} must mention '~', got {result!r}"

    def test_path_without_tilde_is_not_rejected_for_this_rule(self):
        """A normal path does not trigger the tilde rejection."""
        result = _check("foo/bar/baz")
        assert result is None, f"valid path 'foo/bar/baz' must not be rejected: {result!r}"


# ---------------------------------------------------------------------------
# PATH-003  bad Unicode codepoint
# ---------------------------------------------------------------------------


# Each entry is (label, path) -- label is for test ID readability only.
_BAD_CODEPOINT_CASES = [
    ("zero_width_non_joiner", "foo‌bar"),
    ("zero_width_joiner", "foo‍bar"),
    ("ltr_mark", "foo‎bar"),
    ("rtl_mark", "foo‏bar"),
    ("ltr_embedding", "foo‪bar"),
    ("rtl_embedding", "foo‫bar"),
    ("pop_directional", "foo‬bar"),
    ("ltr_override", "foo‭bar"),
    ("rtl_override", "foo‮bar"),
    ("inhibit_symmetric_swapping", "foo⁪bar"),
    ("activate_symmetric_swapping", "foo⁫bar"),
    ("inhibit_arabic_form", "foo⁬bar"),
    ("activate_arabic_form", "foo⁭bar"),
    ("national_digit_shapes", "foo⁮bar"),
    ("nominal_digit_shapes", "foo⁯bar"),
    ("zero_width_no_break_space", "foo﻿bar"),
]


class TestPath003BadUnicodeCodepoint:
    """PATH-003: _CheckLocalPath rejects paths with Unicode normalization codepoints.

    Certain Unicode codepoints allow alternative spellings of '.git' on
    filesystems that normalize Unicode (e.g. Apple HFS+). All such
    codepoints must be rejected.
    """

    @pytest.mark.parametrize("label,path", _BAD_CODEPOINT_CASES)
    def test_bad_codepoint_rejected(self, label, path):
        """Every path with a bad codepoint must produce a non-None error."""
        result = _check(path)
        assert result is not None, f"path with bad codepoint {label!r} must be rejected: {path!r}"

    @pytest.mark.parametrize("label,path", _BAD_CODEPOINT_CASES)
    def test_bad_codepoint_error_mentions_unicode(self, label, path):
        """The error message must mention 'Unicode' so the user understands the cause."""
        result = _check(path)
        assert result is not None
        assert "Unicode" in result, f"error for {label!r} must mention 'Unicode', got {result!r}"


# ---------------------------------------------------------------------------
# PATH-004  newline in path
# ---------------------------------------------------------------------------


_NEWLINE_CASES = [
    ("lf_embedded", "foo\nbar"),
    ("lf_leading", "\nfoo"),
    ("lf_trailing", "foo\n"),
    ("cr_embedded", "foo\rbar"),
    ("cr_leading", "\rfoo"),
    ("cr_trailing", "foo\r"),
    ("crlf_embedded", "foo\r\nbar"),
]


class TestPath004NewlineInPath:
    """PATH-004: _CheckLocalPath rejects any path that contains newline characters.

    Newlines would silently corrupt tools that process newline-delimited
    path lists such as .repo/project.list.
    """

    @pytest.mark.parametrize("label,path", _NEWLINE_CASES)
    def test_newline_path_rejected(self, label, path):
        """Every path containing a newline or carriage-return must be rejected."""
        result = _check(path)
        assert result is not None, f"path with {label!r} must be rejected: {path!r}"

    @pytest.mark.parametrize("label,path", _NEWLINE_CASES)
    def test_newline_error_mentions_newlines(self, label, path):
        """The error message must mention 'Newlines' for clear diagnostics."""
        result = _check(path)
        assert result is not None
        assert "Newlines" in result, f"error for {label!r} must mention 'Newlines', got {result!r}"

    def test_path_without_newline_is_not_rejected_for_this_rule(self):
        """A path that contains neither LF nor CR does not trigger newline rejection."""
        result = _check("valid/path/segment")
        assert result is None, f"valid path must not be rejected: {result!r}"


# ---------------------------------------------------------------------------
# PATH-005  dot component without cwd_dot_ok
# ---------------------------------------------------------------------------


_DOT_COMPONENT_CASES = [
    ("bare_dot", "."),
    ("dot_in_middle", "foo/./bar"),
    ("dot_at_start", "./foo"),
    ("dot_at_end", "foo/."),
    ("multi_dot_segments", "a/./b/./c"),
]


class TestPath005DotComponentWithoutCwdDotOk:
    """PATH-005: _CheckLocalPath rejects a bare '.' component by default.

    When cwd_dot_ok is False (the default), any path whose components
    include '.' must be rejected.  The only exception -- a bare single-dot
    path -- is gated by cwd_dot_ok=True.
    """

    @pytest.mark.parametrize("label,path", _DOT_COMPONENT_CASES)
    def test_dot_component_rejected_by_default(self, label, path):
        """Dot component must be rejected when cwd_dot_ok is False (the default)."""
        result = _check(path)
        assert result is not None, f"path with dot component ({label!r}) must be rejected by default: {path!r}"

    @pytest.mark.parametrize("label,path", _DOT_COMPONENT_CASES)
    def test_dot_component_error_mentions_bad_component(self, label, path):
        """The error message must mention 'bad component' for consistent diagnostics."""
        result = _check(path)
        assert result is not None
        assert "bad component" in result, f"error for {label!r} must mention 'bad component', got {result!r}"

    def test_bare_dot_accepted_when_cwd_dot_ok_true(self):
        """A bare '.' path must be accepted exactly when cwd_dot_ok=True."""
        result = _check(".", cwd_dot_ok=True)
        assert result is None, f"bare '.' with cwd_dot_ok=True must be accepted, got {result!r}"

    def test_dot_in_middle_still_rejected_with_cwd_dot_ok(self):
        """cwd_dot_ok=True only excuses the exact path '.', not embedded dots."""
        result = _check("foo/./bar", cwd_dot_ok=True)
        assert result is not None, "embedded '.' with cwd_dot_ok=True must still be rejected"
        assert "bad component" in result
