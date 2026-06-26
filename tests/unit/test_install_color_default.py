"""Unit tests for the interactive color default applied before `repo init`.

`_ensure_color_default_for_interactive_repo` pre-sets the global git `color.ui`
to `auto` in an interactive (TTY) shell so the vendored repo tool's `repo init`
never shows its "Enable color display in this user account (y/N)?" prompt and
defaults to colorized output. It is gated on a TTY so non-interactive runs and
the test suite never write the global git config.
"""

from __future__ import annotations

from unittest import mock

import pytest

from kanon_cli.core.install import _ensure_color_default_for_interactive_repo


@pytest.mark.unit
def test_sets_color_ui_auto_when_interactive_and_unset() -> None:
    """An interactive shell with no color.ui configured gets color.ui=auto."""
    get_result = mock.Mock(returncode=0, stdout="")
    with (
        mock.patch("sys.stdin.isatty", return_value=True),
        mock.patch("sys.stdout.isatty", return_value=True),
        mock.patch("kanon_cli.core.install.subprocess.run", return_value=get_result) as run,
    ):
        _ensure_color_default_for_interactive_repo()
    run.assert_any_call(["git", "config", "--global", "color.ui", "auto"], check=False)


@pytest.mark.unit
def test_noop_when_not_a_tty() -> None:
    """A non-interactive (non-TTY) shell never touches the global git config."""
    with (
        mock.patch("sys.stdin.isatty", return_value=False),
        mock.patch("sys.stdout.isatty", return_value=True),
        mock.patch("kanon_cli.core.install.subprocess.run") as run,
    ):
        _ensure_color_default_for_interactive_repo()
    run.assert_not_called()


@pytest.mark.unit
def test_noop_when_color_already_set() -> None:
    """An interactive shell with color.ui already set is left unchanged."""
    get_result = mock.Mock(returncode=0, stdout="auto\n")
    with (
        mock.patch("sys.stdin.isatty", return_value=True),
        mock.patch("sys.stdout.isatty", return_value=True),
        mock.patch("kanon_cli.core.install.subprocess.run", return_value=get_result) as run,
    ):
        _ensure_color_default_for_interactive_repo()
    assert run.call_count == 1, "only the color.ui lookup should run; no overwrite"
