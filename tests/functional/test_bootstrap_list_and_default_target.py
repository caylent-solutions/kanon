"""Functional tests for the `kanon bootstrap` list-arm and add-arm deprecation output.

`kanon bootstrap` was removed in a major release (a breaking change). Every
invocation prints one deprecation message to stderr and exits 3. The only
per-invocation part of the message is the "closest replacement" line:

- `kanon bootstrap list` -> the list arm: `kanon list --catalog-source <git-url>@<ref>`
- `kanon bootstrap <entry>` -> the add arm: `kanon add <entry> --catalog-source <git-url>@<ref>`

These tests invoke the running CLI (`python -m kanon_cli`) and assert by key
substrings (never byte-for-byte).
"""

import pytest

from tests.functional.conftest import _run_kanon

# Invocation-independent substrings every deprecation message carries.
_CORE_SUBSTRINGS = (
    "DEPRECATED",
    "major release",
    "breaking change",
    "kanon list",
    "kanon add",
    "kanon install",
    ".kanon",
    "repo-specs",
    "<catalog-metadata>",
    "docs/migration-bootstrap-to-add.md",
)


def _assert_core_message(stderr: str) -> None:
    """Assert the deprecation message's invocation-independent substrings on stderr."""
    for needle in _CORE_SUBSTRINGS:
        assert needle in stderr, f"Expected {needle!r} in deprecation stderr, got: {stderr!r}"


@pytest.mark.functional
class TestBootstrapListArm:
    """`kanon bootstrap list` exits 3 with the list-arm closest-replacement line."""

    def test_bootstrap_list_exits_3(self) -> None:
        result = _run_kanon("bootstrap", "list")
        assert result.returncode == 3, f"Expected exit code 3, got {result.returncode}.\nstderr: {result.stderr!r}"

    def test_bootstrap_list_core_message_on_stderr(self) -> None:
        result = _run_kanon("bootstrap", "list")
        assert result.returncode == 3
        _assert_core_message(result.stderr)

    def test_bootstrap_list_closest_replacement_uses_kanon_list(self) -> None:
        result = _run_kanon("bootstrap", "list")
        assert result.returncode == 3
        assert "kanon list --catalog-source <git-url>@<ref>" in result.stderr, (
            f"Expected the list-arm closest-replacement line, got: {result.stderr!r}"
        )

    def test_bootstrap_list_nothing_on_stdout(self) -> None:
        result = _run_kanon("bootstrap", "list")
        assert result.returncode == 3
        assert result.stdout == "", f"Expected empty stdout, got: {result.stdout!r}"


@pytest.mark.functional
class TestBootstrapAddArm:
    """`kanon bootstrap <entry>` exits 3 with the add-arm closest-replacement line."""

    def test_bootstrap_entry_exits_3(self) -> None:
        result = _run_kanon("bootstrap", "kanon")
        assert result.returncode == 3, f"Expected exit code 3, got {result.returncode}.\nstderr: {result.stderr!r}"

    def test_bootstrap_entry_core_message_on_stderr(self) -> None:
        result = _run_kanon("bootstrap", "kanon")
        assert result.returncode == 3
        _assert_core_message(result.stderr)

    def test_bootstrap_entry_closest_replacement_names_entry(self) -> None:
        result = _run_kanon("bootstrap", "kanon")
        assert result.returncode == 3
        assert "kanon add kanon --catalog-source <git-url>@<ref>" in result.stderr, (
            f"Expected the add-arm closest-replacement line naming the entry, got: {result.stderr!r}"
        )

    @pytest.mark.parametrize("entry", ["kanon", "acme-tools", "my-package"])
    def test_various_entries_use_add_arm(self, entry: str) -> None:
        result = _run_kanon("bootstrap", entry)
        assert result.returncode == 3
        assert f"kanon add {entry} --catalog-source <git-url>@<ref>" in result.stderr, (
            f"Expected the add-arm closest-replacement line for entry {entry!r}, got: {result.stderr!r}"
        )

    def test_bootstrap_entry_nothing_on_stdout(self) -> None:
        result = _run_kanon("bootstrap", "kanon")
        assert result.returncode == 3
        assert result.stdout == "", f"Expected empty stdout, got: {result.stdout!r}"

    def test_bootstrap_message_only_on_stderr_not_stdout(self) -> None:
        """Channel discipline: the deprecation message goes to stderr, not stdout."""
        result = _run_kanon("bootstrap", "kanon")
        assert result.returncode == 3
        assert "DEPRECATED" in result.stderr
        assert "DEPRECATED" not in result.stdout, f"DEPRECATED must not appear on stdout, got: {result.stdout!r}"
