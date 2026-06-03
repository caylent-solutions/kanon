"""Unit tests for the ``_emit_json_payload`` helper in ``kanon_cli.cli``.

Verifies the atomic write+flush contract for JSON output (DEFECT-002).

All tests in this module are :pymark:`unit` -- they exercise ``_emit_json_payload``
in isolation, without spawning subprocesses or touching the network.

AC-FUNC-001: helper exists in cli.py with the required signature.
AC-FUNC-004: helper docstring matches the spec D3 contract text.
AC-FUNC-005: helper uses sys.stdout.write + sys.stdout.flush; no time.sleep,
             no fd manipulation, no exception swallowing.
"""

from __future__ import annotations

import io
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from kanon_cli.cli import _emit_json_payload


# ---------------------------------------------------------------------------
# AC-FUNC-001: signature and existence
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEmitJsonPayloadSignature:
    """_emit_json_payload is importable from cli and has the correct signature."""

    def test_function_is_importable(self) -> None:
        """_emit_json_payload can be imported from kanon_cli.cli."""
        from kanon_cli.cli import _emit_json_payload as fn

        assert callable(fn)

    def test_default_sort_keys_is_true(self) -> None:
        """Default sort_keys=True produces lexicographically sorted keys."""
        buf = io.StringIO()
        payload = {"z": 1, "a": 2}
        with patch("sys.stdout", buf):
            _emit_json_payload(payload)
        output = buf.getvalue()
        parsed = json.loads(output)
        keys = list(parsed.keys())
        assert keys == sorted(keys)

    def test_default_indent_is_none_compact_output(self) -> None:
        """Default indent=None produces compact JSON (no pretty indentation)."""
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _emit_json_payload({"key": "value"})
        output = buf.getvalue().rstrip("\n")
        # Compact JSON has no leading spaces on new lines
        assert "\n" not in output

    def test_sort_keys_false_preserves_insertion_order(self) -> None:
        """sort_keys=False preserves the original key insertion order."""
        buf = io.StringIO()
        payload = {"z": 1, "a": 2}
        with patch("sys.stdout", buf):
            _emit_json_payload(payload, sort_keys=False)
        output = buf.getvalue()
        parsed = json.loads(output)
        keys = list(parsed.keys())
        assert keys == ["z", "a"]

    def test_indent_kwarg_produces_pretty_output(self) -> None:
        """indent=2 produces multi-line pretty-printed JSON."""
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _emit_json_payload({"a": 1}, indent=2)
        output = buf.getvalue()
        assert "\n" in output.rstrip("\n")

    def test_returns_none(self) -> None:
        """_emit_json_payload returns None (no return value)."""
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            result = _emit_json_payload({"key": "val"})
        assert result is None


# ---------------------------------------------------------------------------
# AC-FUNC-005: atomic write + flush, no temporal logic, no exception swallowing
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEmitJsonPayloadAtomicWriteFlush:
    """The helper performs a single sys.stdout.write followed by sys.stdout.flush."""

    def test_single_write_call_for_list_payload(self) -> None:
        """A list payload is written via a single sys.stdout.write call."""
        mock_stdout = MagicMock()
        with patch("sys.stdout", mock_stdout):
            _emit_json_payload([1, 2, 3])
        write_calls = [c for c in mock_stdout.method_calls if c[0] == "write"]
        assert len(write_calls) == 1

    def test_single_write_call_for_dict_payload(self) -> None:
        """A dict payload is written via a single sys.stdout.write call."""
        mock_stdout = MagicMock()
        with patch("sys.stdout", mock_stdout):
            _emit_json_payload({"findings": []})
        write_calls = [c for c in mock_stdout.method_calls if c[0] == "write"]
        assert len(write_calls) == 1

    def test_flush_called_after_write(self) -> None:
        """sys.stdout.flush() is called after the write."""
        mock_stdout = MagicMock()
        with patch("sys.stdout", mock_stdout):
            _emit_json_payload({"k": "v"})
        method_names = [c[0] for c in mock_stdout.method_calls]
        assert "write" in method_names
        assert "flush" in method_names
        write_pos = next(i for i, n in enumerate(method_names) if n == "write")
        flush_pos = next(i for i, n in enumerate(method_names) if n == "flush")
        assert flush_pos > write_pos, "flush must be called after write"

    def test_write_argument_ends_with_newline(self) -> None:
        """The argument passed to sys.stdout.write ends with exactly one newline."""
        mock_stdout = MagicMock()
        with patch("sys.stdout", mock_stdout):
            _emit_json_payload([{"a": 1}])
        write_args = [c.args[0] for c in mock_stdout.method_calls if c[0] == "write"]
        assert len(write_args) == 1
        written = write_args[0]
        assert written.endswith("\n")
        assert not written.endswith("\n\n")

    def test_write_argument_is_valid_json_plus_newline(self) -> None:
        """The written string, stripped of its trailing newline, is valid JSON."""
        mock_stdout = MagicMock()
        payload = [{"name": "alpha", "version": "1.0.0"}]
        with patch("sys.stdout", mock_stdout):
            _emit_json_payload(payload)
        write_args = [c.args[0] for c in mock_stdout.method_calls if c[0] == "write"]
        written = write_args[0]
        parsed = json.loads(written.rstrip("\n"))
        assert parsed == payload

    def test_no_exception_swallowing_for_type_error(self) -> None:
        """TypeError from a non-serialisable payload propagates to the caller."""
        buf = io.StringIO()

        class _Unserializable:
            pass

        with patch("sys.stdout", buf):
            with pytest.raises(TypeError):
                _emit_json_payload(_Unserializable())

    def test_broken_pipe_propagates(self) -> None:
        """BrokenPipeError from sys.stdout.write propagates to the caller."""
        mock_stdout = MagicMock()
        mock_stdout.write.side_effect = BrokenPipeError("pipe closed")
        with patch("sys.stdout", mock_stdout):
            with pytest.raises(BrokenPipeError):
                _emit_json_payload({"key": "value"})


# ---------------------------------------------------------------------------
# AC-FUNC-004: docstring matches spec D3 contract text
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEmitJsonPayloadDocstring:
    """The docstring mentions the D3 contract key phrases."""

    def test_docstring_mentions_single_json_document(self) -> None:
        """Docstring references 'single JSON document' per spec D3."""
        doc = _emit_json_payload.__doc__ or ""
        assert "single JSON document" in doc

    def test_docstring_mentions_stderr_warning_channel(self) -> None:
        """Docstring references stderr containing warnings per spec D3."""
        doc = _emit_json_payload.__doc__ or ""
        assert "stderr" in doc

    def test_docstring_mentions_never_use_2_and_1(self) -> None:
        """Docstring contains the D3 directive about not using 2>&1."""
        doc = _emit_json_payload.__doc__ or ""
        assert "2>&1" in doc


# ---------------------------------------------------------------------------
# Output content correctness
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEmitJsonPayloadOutputContent:
    """Verify the actual content written to stdout for various payloads."""

    def test_list_payload_produces_json_array(self) -> None:
        """A list payload results in a JSON array string."""
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _emit_json_payload([1, 2, 3])
        parsed = json.loads(buf.getvalue())
        assert parsed == [1, 2, 3]

    def test_dict_payload_produces_json_object(self) -> None:
        """A dict payload results in a JSON object string."""
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _emit_json_payload({"findings": []})
        parsed = json.loads(buf.getvalue())
        assert parsed == {"findings": []}

    def test_empty_list_produces_empty_array(self) -> None:
        """An empty list produces the literal '[]'."""
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _emit_json_payload([])
        assert buf.getvalue().rstrip("\n") == "[]"

    def test_empty_dict_produces_empty_object(self) -> None:
        """An empty dict produces the literal '{}'."""
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _emit_json_payload({})
        assert buf.getvalue().rstrip("\n") == "{}"

    def test_nested_structure_round_trips(self) -> None:
        """Complex nested structure is round-tripped through JSON serialisation."""
        payload: Any = {
            "findings": [
                {"kind": "error", "code": "E001", "message": "Something wrong."},
                {"kind": "warn", "code": "W001", "message": "Consider this."},
            ]
        }
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _emit_json_payload(payload)
        parsed = json.loads(buf.getvalue())
        assert parsed == payload

    @pytest.mark.parametrize(
        "payload,expected_sentinel",
        [
            ([{"a": 1}], "["),
            ({"b": 2}, "{"),
            ([], "["),
            ({}, "{"),
        ],
    )
    def test_output_starts_with_correct_sentinel(self, payload: Any, expected_sentinel: str) -> None:
        """Output begins with '[' for arrays and '{' for objects."""
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _emit_json_payload(payload)
        assert buf.getvalue().startswith(expected_sentinel)

    def test_compact_separators_used_by_default(self) -> None:
        """Default output uses compact separators (no extra spaces)."""
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _emit_json_payload({"a": 1, "b": 2})
        output = buf.getvalue().rstrip("\n")
        # Compact JSON: no space after colon, no space after comma
        assert ": " not in output
        assert ", " not in output
