"""Unit tests for the _ParseList method in manifest_xml.XmlManifest.

Covers:
  AC-TEST-001  comma separator works
  AC-TEST-002  space separator works
  AC-TEST-003  mixed separators work
  AC-TEST-004  empty tokens are skipped
  AC-TEST-005  notdefault exclusion behaves per spec

  AC-FUNC-001  _ParseList tokenization is robust across separator styles
  AC-CHANNEL-001  no stdout or stderr emitted by _ParseList (pure parsing)

All tests are marked @pytest.mark.unit.

_ParseList is a pure tokenizer: it uses re.split(r"[,\\s]+", field) and
discards empty strings.  It does not use instance state, so it can be
called with None as the receiver.
"""

import pytest

from kanon_cli.repo.manifest_xml import XmlManifest


def _parse(field: str) -> list:
    """Invoke XmlManifest._ParseList without constructing a full manifest instance.

    _ParseList only uses the ``field`` argument and never accesses ``self``,
    so passing None as the receiver is safe.

    Args:
        field: The raw groups/list string to tokenize.

    Returns:
        List of non-empty tokens extracted from ``field``.
    """
    return XmlManifest._ParseList(None, field)


# ---------------------------------------------------------------------------
# AC-TEST-001: comma separator works
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "field, expected",
    [
        ("a,b,c", ["a", "b", "c"]),
        ("foo,bar", ["foo", "bar"]),
        ("x,y,z,w", ["x", "y", "z", "w"]),
        ("single", ["single"]),
        ("notdefault,platform-arm", ["notdefault", "platform-arm"]),
    ],
)
def test_parselist_comma_separator(field, expected):
    """AC-TEST-001: comma-separated tokens are split correctly."""
    result = _parse(field)
    assert result == expected, f"_ParseList({field!r}) returned {result!r}, expected {expected!r}"


# ---------------------------------------------------------------------------
# AC-TEST-002: space separator works
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "field, expected",
    [
        ("a b c", ["a", "b", "c"]),
        ("foo bar", ["foo", "bar"]),
        ("x y z w", ["x", "y", "z", "w"]),
        ("notdefault platform-arm", ["notdefault", "platform-arm"]),
        ("a\tb\tc", ["a", "b", "c"]),
        ("a\nb\nc", ["a", "b", "c"]),
    ],
)
def test_parselist_space_separator(field, expected):
    """AC-TEST-002: whitespace-separated tokens are split correctly."""
    result = _parse(field)
    assert result == expected, f"_ParseList({field!r}) returned {result!r}, expected {expected!r}"


# ---------------------------------------------------------------------------
# AC-TEST-003: mixed separators work
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "field, expected",
    [
        ("a, b  c,d", ["a", "b", "c", "d"]),
        ("foo,  bar  baz", ["foo", "bar", "baz"]),
        ("x ,y, z", ["x", "y", "z"]),
        ("notdefault, platform-arm linux", ["notdefault", "platform-arm", "linux"]),
        ("all, name:proj path:proj/path", ["all", "name:proj", "path:proj/path"]),
    ],
)
def test_parselist_mixed_separators(field, expected):
    """AC-TEST-003: mixed comma-and-whitespace separators all split correctly."""
    result = _parse(field)
    assert result == expected, f"_ParseList({field!r}) returned {result!r}, expected {expected!r}"


# ---------------------------------------------------------------------------
# AC-TEST-004: empty tokens are skipped
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "field, expected",
    [
        ("", []),
        ("   ", []),
        ("\t\n", []),
        ("a,,b", ["a", "b"]),
        ("a,  ,b", ["a", "b"]),
        (",,,", []),
        ("a,,b,  ,c", ["a", "b", "c"]),
        (" a , b , c ", ["a", "b", "c"]),
    ],
)
def test_parselist_empty_tokens_are_skipped(field, expected):
    """AC-TEST-004: empty tokens produced by consecutive separators are discarded."""
    result = _parse(field)
    assert result == expected, f"_ParseList({field!r}) returned {result!r}, expected {expected!r}"


# ---------------------------------------------------------------------------
# AC-TEST-005: notdefault exclusion behaves per spec
#
# The _ParseList function tokenizes the raw attribute string.  The
# "notdefault" token must appear verbatim in the result; the exclusion
# behavior (preventing "default" from being added to expanded_project_groups)
# is handled downstream in Project.MatchesGroups and is not part of
# _ParseList itself.
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "field, expected",
    [
        ("notdefault", ["notdefault"]),
        ("notdefault,platform-arm", ["notdefault", "platform-arm"]),
        ("notdefault platform-arm", ["notdefault", "platform-arm"]),
        ("notdefault, platform-arm, linux", ["notdefault", "platform-arm", "linux"]),
        ("group1,notdefault,group2", ["group1", "notdefault", "group2"]),
    ],
)
def test_parselist_notdefault_token_preserved(field, expected):
    """AC-TEST-005: 'notdefault' is tokenized as a regular string token.

    _ParseList must not swallow, transform, or re-order the 'notdefault'
    sentinel -- it must appear exactly where it was in the input.
    """
    result = _parse(field)
    assert result == expected, f"_ParseList({field!r}) returned {result!r}, expected {expected!r}"
    assert "notdefault" in result, f"'notdefault' token missing from result: {result!r}"


@pytest.mark.unit
def test_parselist_notdefault_not_added_implicitly():
    """AC-TEST-005: _ParseList never injects 'notdefault' when it is absent.

    Only tokenizes; it never manufactures tokens that were not in the input.
    """
    result = _parse("group1,group2")
    assert "notdefault" not in result, f"'notdefault' must not appear in result when not in input; got {result!r}"


# ---------------------------------------------------------------------------
# AC-FUNC-001: tokenization is robust across separator styles
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parselist_leading_trailing_separators_discarded():
    """AC-FUNC-001: leading and trailing separators do not produce empty tokens."""
    result = _parse(",a,b,")
    assert "" not in result, f"empty string must not appear in result: {result!r}"
    assert result == ["a", "b"], f"expected ['a', 'b'], got {result!r}"


@pytest.mark.unit
def test_parselist_consecutive_mixed_separators_discarded():
    """AC-FUNC-001: consecutive mixed separators collapse into one split point."""
    result = _parse("a, , ,b")
    assert "" not in result, f"empty string must not appear in result: {result!r}"
    assert result == ["a", "b"], f"expected ['a', 'b'], got {result!r}"


@pytest.mark.unit
def test_parselist_returns_list():
    """AC-FUNC-001: _ParseList always returns a list, never None or another type."""
    result = _parse("")
    assert isinstance(result, list), f"_ParseList must return a list, got {type(result)!r}"


@pytest.mark.unit
def test_parselist_preserves_token_content():
    """AC-FUNC-001: tokens are returned verbatim without case change or stripping.

    Only separator characters are consumed; token text is passed through
    unchanged.
    """
    result = _parse("name:MyProject path:src/MyProject")
    assert result == ["name:MyProject", "path:src/MyProject"], (
        f"token content must be preserved verbatim, got {result!r}"
    )


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: no stdout or stderr emitted
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "field",
    [
        "",
        "a,b,c",
        "a b c",
        "notdefault,platform-arm",
        ",,",
        " a , b ",
    ],
)
def test_parselist_produces_no_output(capsys, field):
    """AC-CHANNEL-001: _ParseList is a silent pure function -- no stdout or stderr."""
    _parse(field)
    captured = capsys.readouterr()
    assert captured.out == "", f"_ParseList({field!r}) wrote to stdout: {captured.out!r}"
    assert captured.err == "", f"_ParseList({field!r}) wrote to stderr: {captured.err!r}"
