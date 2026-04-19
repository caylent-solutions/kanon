"""Integration tests for kanon install required variable validation.

Verifies that the install command fails fast with exit code 1 and a
clear error message naming the missing variable when any of the three
required KANON_SOURCE_* variables is absent from the .kanon file.

AC-TEST-001: install fails fast with clear message when KANON_SOURCE_*_URL is missing
AC-TEST-002: install fails fast when KANON_SOURCE_*_REVISION is missing
AC-TEST-003: install fails fast when KANON_SOURCE_*_PATH is missing
AC-TEST-004: install succeeds with all three required variables supplied
AC-FUNC-001: Every required variable must be present or install exits 1 naming the missing variable
AC-CHANNEL-001: Error output goes to stderr only; stdout is clean on failure
"""

import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.cli import main


_SOURCE_NAME = "testsource"
_VALID_URL = "https://example.com/repo.git"
_VALID_REVISION = "main"
_VALID_PATH = "repo-specs/manifest.xml"

_ALL_THREE_VARS = (
    f"KANON_SOURCE_{_SOURCE_NAME}_URL={_VALID_URL}\n"
    f"KANON_SOURCE_{_SOURCE_NAME}_REVISION={_VALID_REVISION}\n"
    f"KANON_SOURCE_{_SOURCE_NAME}_PATH={_VALID_PATH}\n"
)

_MISSING_URL = (
    f"KANON_SOURCE_{_SOURCE_NAME}_REVISION={_VALID_REVISION}\nKANON_SOURCE_{_SOURCE_NAME}_PATH={_VALID_PATH}\n"
)

_MISSING_REVISION = f"KANON_SOURCE_{_SOURCE_NAME}_URL={_VALID_URL}\nKANON_SOURCE_{_SOURCE_NAME}_PATH={_VALID_PATH}\n"

_MISSING_PATH = (
    f"KANON_SOURCE_{_SOURCE_NAME}_URL={_VALID_URL}\nKANON_SOURCE_{_SOURCE_NAME}_REVISION={_VALID_REVISION}\n"
)


def _write_kanonenv(directory: pathlib.Path, content: str) -> pathlib.Path:
    """Write a .kanon file in directory with the given content and return its path.

    Args:
        directory: Directory in which to create the .kanon file.
        content: File content to write.

    Returns:
        Absolute path to the written .kanon file.
    """
    kanonenv = directory / ".kanon"
    kanonenv.write_text(content)
    return kanonenv.resolve()


@pytest.mark.integration
class TestInstallMissingRequiredVars:
    """AC-TEST-001/002/003 and AC-FUNC-001: install exits 1 naming the missing variable."""

    @pytest.mark.parametrize(
        "content,missing_var_suffix",
        [
            (_MISSING_URL, f"KANON_SOURCE_{_SOURCE_NAME}_URL"),
            (_MISSING_REVISION, f"KANON_SOURCE_{_SOURCE_NAME}_REVISION"),
            (_MISSING_PATH, f"KANON_SOURCE_{_SOURCE_NAME}_PATH"),
        ],
        ids=["missing_URL", "missing_REVISION", "missing_PATH"],
    )
    def test_install_exits_1_when_required_var_missing(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
        content: str,
        missing_var_suffix: str,
    ) -> None:
        """AC-TEST-001/002/003/AC-FUNC-001: exits 1 with error naming the missing variable."""
        kanonenv = _write_kanonenv(tmp_path, content)

        with pytest.raises(SystemExit) as exc_info:
            main(["install", str(kanonenv)])

        assert exc_info.value.code == 1, (
            f"Expected exit code 1 when {missing_var_suffix!r} is missing, got {exc_info.value.code}"
        )

        captured = capsys.readouterr()
        assert missing_var_suffix in captured.err, (
            f"Expected error message naming {missing_var_suffix!r} in stderr, got stderr={captured.err!r}"
        )

    @pytest.mark.parametrize(
        "content,missing_var_suffix",
        [
            (_MISSING_URL, f"KANON_SOURCE_{_SOURCE_NAME}_URL"),
            (_MISSING_REVISION, f"KANON_SOURCE_{_SOURCE_NAME}_REVISION"),
            (_MISSING_PATH, f"KANON_SOURCE_{_SOURCE_NAME}_PATH"),
        ],
        ids=["missing_URL_no_stdout", "missing_REVISION_no_stdout", "missing_PATH_no_stdout"],
    )
    def test_install_error_on_stderr_not_stdout(
        self,
        tmp_path: pathlib.Path,
        capsys: pytest.CaptureFixture,
        content: str,
        missing_var_suffix: str,
    ) -> None:
        """AC-CHANNEL-001: error output goes to stderr only; stdout is clean on failure."""
        kanonenv = _write_kanonenv(tmp_path, content)

        with pytest.raises(SystemExit):
            main(["install", str(kanonenv)])

        captured = capsys.readouterr()
        assert missing_var_suffix not in captured.out, (
            f"Error for missing {missing_var_suffix!r} must not appear on stdout, got stdout={captured.out!r}"
        )
        assert "Error" in captured.err, (
            f"Expected 'Error' prefix in stderr when {missing_var_suffix!r} is missing, got stderr={captured.err!r}"
        )


@pytest.mark.integration
class TestInstallAllVarsPresent:
    """AC-TEST-004: install does not exit 1 when all three required variables are supplied."""

    def test_install_proceeds_when_all_required_vars_supplied(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """AC-TEST-004: install does not raise SystemExit when all required vars are present."""
        kanonenv = _write_kanonenv(tmp_path, _ALL_THREE_VARS)

        with patch("kanon_cli.commands.install.install") as mock_install:
            main(["install", str(kanonenv)])

        mock_install.assert_called_once()
        called_path: pathlib.Path = mock_install.call_args[0][0]
        assert called_path.is_absolute()
        assert called_path == kanonenv
