"""Tests for version constraint error message correctness.

Covers AC-TEST-001: when kanon receives an invalid version constraint such as
``=*``, stderr must contain the string ``invalid version constraint``.

KS-26 scenario: KANON_SOURCE_pep_REVISION==* in .kanon yields revision ``=*``,
which is not a valid PEP 440 constraint operator. The ``=`` operator (single
equals) is not defined in PEP 440; the correct form is ``==``. Kanon must
detect this as an invalid constraint and emit ``invalid version constraint``
rather than passing it through as a plain branch name that produces a
misleading ``revision not found`` error from git.
"""

from unittest.mock import MagicMock, patch

import pytest

from kanon_cli.version import _resolve_constraint_from_tags, is_version_constraint, resolve_version


@pytest.mark.unit
class TestInvalidEqualsConstraintDetected:
    """Verify that ``=*`` is detected as a version constraint (not a plain ref)."""

    def test_single_equals_wildcard_is_detected_as_constraint(self) -> None:
        """``=*`` must be identified as a version constraint attempt."""
        assert is_version_constraint("=*") is True

    def test_single_equals_version_is_detected_as_constraint(self) -> None:
        """``=1.0.0`` must be identified as a version constraint attempt."""
        assert is_version_constraint("=1.0.0") is True

    def test_double_equals_wildcard_still_detected(self) -> None:
        """``==*`` remains a valid constraint (double-equals wildcard)."""
        assert is_version_constraint("==*") is True


@pytest.mark.unit
class TestInvalidConstraintErrorMessage:
    """Verify that invalid version constraints emit ``invalid version constraint`` in stderr."""

    def test_resolve_constraint_raises_invalid_version_constraint_for_equals_star(self) -> None:
        """_resolve_constraint_from_tags raises ValueError with 'invalid version constraint' for ``=*``."""
        available_tags = ["refs/tags/1.0.0", "refs/tags/1.1.0"]
        with pytest.raises(ValueError, match="invalid version constraint"):
            _resolve_constraint_from_tags("=*", available_tags)

    def test_resolve_constraint_raises_invalid_version_constraint_for_equals_version(self) -> None:
        """_resolve_constraint_from_tags raises ValueError with 'invalid version constraint' for ``=1.0.0``."""
        available_tags = ["refs/tags/1.0.0", "refs/tags/1.1.0"]
        with pytest.raises(ValueError, match="invalid version constraint"):
            _resolve_constraint_from_tags("=1.0.0", available_tags)

    def test_resolve_version_writes_invalid_constraint_to_stderr_and_exits(self, capsys: pytest.CaptureFixture) -> None:
        """resolve_version writes ``invalid version constraint`` to stderr and exits non-zero for ``=*``."""
        tags = ["refs/tags/1.0.0", "refs/tags/1.1.0"]
        mock_result = MagicMock(returncode=0, stdout="\n".join(f"abc\t{t}" for t in tags), stderr="")
        with patch("kanon_cli.version.subprocess.run", return_value=mock_result):
            with pytest.raises(SystemExit) as exc_info:
                resolve_version("https://example.com/repo.git", "=*")
        assert exc_info.value.code != 0
        captured = capsys.readouterr()
        assert "invalid version constraint" in captured.err
