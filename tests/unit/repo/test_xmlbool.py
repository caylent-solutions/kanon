"""Unit tests for the XmlBool utility function in manifest_xml.

Covers:
  AC-TEST-001  yes/true/1 parse as true
  AC-TEST-002  no/false/0 parse as false
  AC-TEST-003  empty value uses the supplied default
  AC-TEST-004  invalid value emits a warning to stderr and uses the default

  AC-FUNC-001  XmlBool accepts only the documented truthy/falsy values
  AC-CHANNEL-001  warnings go to stderr; stdout is not polluted

All tests are marked @pytest.mark.unit and use real xml.dom.minidom nodes --
no mocking of the XML parser itself.
"""

import xml.dom.minidom

import pytest

from kanon_cli.repo.manifest_xml import XmlBool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _node(attr_value: str):
    """Return a real DOM element with ``attr`` set to *attr_value*."""
    doc = xml.dom.minidom.parseString(f'<item attr="{attr_value}"/>'.encode())
    return doc.documentElement


def _node_no_attr():
    """Return a real DOM element that has no ``attr`` attribute at all."""
    doc = xml.dom.minidom.parseString(b"<item/>")
    return doc.documentElement


# ---------------------------------------------------------------------------
# AC-TEST-001: truthy canonical values
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw",
    ["yes", "true", "1", "YES", "True", "TRUE", "Yes"],
)
def test_xmlbool_truthy_values(raw):
    """AC-TEST-001: yes/true/1 (any case) parse as True."""
    node = _node(raw)
    result = XmlBool(node, "attr")
    assert result is True, f"expected True for {raw!r}, got {result!r}"


# ---------------------------------------------------------------------------
# AC-TEST-002: falsy canonical values
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw",
    ["no", "false", "0", "NO", "False", "FALSE", "No"],
)
def test_xmlbool_falsy_values(raw):
    """AC-TEST-002: no/false/0 (any case) parse as False."""
    node = _node(raw)
    result = XmlBool(node, "attr")
    assert result is False, f"expected False for {raw!r}, got {result!r}"


# ---------------------------------------------------------------------------
# AC-TEST-003: empty attribute / missing attribute uses default
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "default",
    [None, True, False],
)
def test_xmlbool_empty_attr_uses_default(default):
    """AC-TEST-003: an empty attribute value returns the supplied default."""
    node = _node("")
    result = XmlBool(node, "attr", default=default)
    assert result is default, f"expected default {default!r}, got {result!r}"


@pytest.mark.unit
def test_xmlbool_missing_attr_uses_default():
    """AC-TEST-003: a missing attribute (getAttribute returns '') uses default."""
    node = _node_no_attr()
    result = XmlBool(node, "attr", default=False)
    assert result is False


# ---------------------------------------------------------------------------
# AC-TEST-004: invalid value warns to stderr and uses default
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "invalid",
    ["maybe", "on", "off", "2", "tru", "fals", "yep", "nope", "enable", "disable"],
)
def test_xmlbool_invalid_value_uses_default(capsys, invalid):
    """AC-TEST-004: unrecognised value emits a warning to stderr and returns default."""
    node = _node(invalid)
    result = XmlBool(node, "attr", default=None)
    assert result is None, f"expected default None for {invalid!r}, got {result!r}"
    captured = capsys.readouterr()
    assert "warning" in captured.err.lower(), f"expected a warning on stderr for {invalid!r}, got: {captured.err!r}"
    assert captured.out == "", f"expected empty stdout for {invalid!r}, got: {captured.out!r}"


@pytest.mark.unit
@pytest.mark.parametrize("default", [True, False])
def test_xmlbool_invalid_value_default_variants(capsys, default):
    """AC-TEST-004: invalid value returns whichever default is supplied."""
    node = _node("maybe")
    result = XmlBool(node, "attr", default=default)
    assert result is default
    captured = capsys.readouterr()
    assert "warning" in captured.err.lower()
    assert captured.out == ""


# ---------------------------------------------------------------------------
# AC-FUNC-001: only documented truthy/falsy values are accepted; all others
# trigger the warning-and-default path
# ---------------------------------------------------------------------------


DOCUMENTED_TRUE = {"yes", "true", "1"}
DOCUMENTED_FALSE = {"no", "false", "0"}


@pytest.mark.unit
def test_xmlbool_truthy_set_is_exactly_documented():
    """AC-FUNC-001: values outside the documented truthy set do NOT return True."""
    candidates = ["on", "enable", "enabled", "t", "y", "affirmative"]
    for val in candidates:
        node = _node(val)
        result = XmlBool(node, "attr", default=None)
        assert result is not True, f"XmlBool unexpectedly returned True for undocumented value {val!r}"


@pytest.mark.unit
def test_xmlbool_falsy_set_is_exactly_documented():
    """AC-FUNC-001: values outside the documented falsy set do NOT return False."""
    candidates = ["off", "disable", "disabled", "f", "n", "negative"]
    for val in candidates:
        node = _node(val)
        result = XmlBool(node, "attr", default=None)
        assert result is not False, f"XmlBool unexpectedly returned False for undocumented value {val!r}"


# ---------------------------------------------------------------------------
# AC-CHANNEL-001: stdout vs stderr channel discipline
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_xmlbool_valid_truthy_no_stdout_stderr(capsys):
    """AC-CHANNEL-001: valid truthy values produce no output on either channel."""
    node = _node("true")
    XmlBool(node, "attr")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.unit
def test_xmlbool_valid_falsy_no_stdout_stderr(capsys):
    """AC-CHANNEL-001: valid falsy values produce no output on either channel."""
    node = _node("false")
    XmlBool(node, "attr")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


@pytest.mark.unit
def test_xmlbool_invalid_warning_goes_to_stderr_not_stdout(capsys):
    """AC-CHANNEL-001: the invalid-value warning appears on stderr, not stdout."""
    node = _node("bogus")
    XmlBool(node, "attr", default=False)
    captured = capsys.readouterr()
    assert "warning" in captured.err.lower()
    assert "bogus" in captured.err
    assert captured.out == ""
