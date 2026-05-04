"""Unit tests for resolve_repo_dir absolute path conversion.

Verifies that resolve_repo_dir() always returns an absolute path, preventing
ManifestParseError when the default relative .repo path is used with RepoClient.

AC-TEST-001: Unit test covers the case where repo_dir defaults to `.repo`
             (relative); after fix, RepoClient receives an absolute path.
AC-TEST-002: Unit test covers the case where an explicit absolute repo_dir is
             passed; behaviour unchanged.
"""

import os

import pytest


@pytest.mark.unit
class TestResolveRepoDirAbsoluteConversion:
    """Tests for resolve_repo_dir ensuring it always returns an absolute path."""

    def test_default_repo_dir_is_absolute(self) -> None:
        """AC-TEST-001: When no flag or env var is set, returned path must be absolute.

        The default KANONENV_REPO_DIR_DEFAULT is '.repo' (relative).
        After the fix, resolve_repo_dir() must convert it to an absolute path
        using os.path.abspath(), so RepoClient receives an absolute path and
        does not raise ManifestParseError.
        """
        from kanon_cli.commands.repo import resolve_repo_dir

        result = resolve_repo_dir(flag_value=None, env={})

        assert os.path.isabs(result), (
            f"resolve_repo_dir() returned a relative path {result!r}; "
            "expected an absolute path to prevent ManifestParseError"
        )

    def test_relative_flag_value_is_converted_to_absolute(self) -> None:
        """AC-TEST-001: An explicit relative --repo-dir flag must be converted to absolute.

        When the caller passes a relative path via --repo-dir, resolve_repo_dir()
        must still return an absolute path so RepoClient does not raise
        ManifestParseError.
        """
        from kanon_cli.commands.repo import resolve_repo_dir

        result = resolve_repo_dir(flag_value=".repo", env={})

        assert os.path.isabs(result), (
            f"resolve_repo_dir() returned a relative path {result!r}; "
            "expected an absolute path to prevent ManifestParseError"
        )

    def test_absolute_flag_value_is_returned_unchanged(self, tmp_path) -> None:
        """AC-TEST-002: An explicit absolute --repo-dir flag must be returned unchanged.

        When the caller passes an absolute path via --repo-dir, resolve_repo_dir()
        must return it unchanged.
        """
        from kanon_cli.commands.repo import resolve_repo_dir

        abs_path = str(tmp_path / ".repo")
        result = resolve_repo_dir(flag_value=abs_path, env={})

        assert result == abs_path, f"resolve_repo_dir() returned {result!r}; expected {abs_path!r}"

    def test_relative_env_var_is_converted_to_absolute(self) -> None:
        """AC-TEST-001: A relative KANON_REPO_DIR env var must be converted to absolute.

        When the caller provides a relative path via the KANON_REPO_DIR env var,
        resolve_repo_dir() must still return an absolute path.
        """
        from kanon_cli.commands.repo import resolve_repo_dir
        from kanon_cli.constants import KANON_REPO_DIR_ENV

        result = resolve_repo_dir(flag_value=None, env={KANON_REPO_DIR_ENV: "my-relative/.repo"})

        assert os.path.isabs(result), (
            f"resolve_repo_dir() returned a relative path {result!r}; "
            "expected an absolute path to prevent ManifestParseError"
        )

    def test_absolute_env_var_is_returned_unchanged(self, tmp_path) -> None:
        """AC-TEST-002: An absolute KANON_REPO_DIR env var must be returned unchanged.

        When the caller provides an absolute path via KANON_REPO_DIR,
        resolve_repo_dir() must return it unchanged.
        """
        from kanon_cli.commands.repo import resolve_repo_dir
        from kanon_cli.constants import KANON_REPO_DIR_ENV

        abs_path = str(tmp_path / "custom" / ".repo")
        result = resolve_repo_dir(flag_value=None, env={KANON_REPO_DIR_ENV: abs_path})

        assert result == abs_path, f"resolve_repo_dir() returned {result!r}; expected {abs_path!r}"

    @pytest.mark.parametrize(
        "input_path,description",
        [
            (".repo", "default relative path"),
            ("relative/path/.repo", "deeper relative path"),
            ("./local/.repo", "explicit-dot relative path"),
        ],
    )
    def test_various_relative_paths_become_absolute(self, input_path: str, description: str) -> None:
        """AC-TEST-001: Parametrized relative inputs must all produce absolute outputs.

        Covers the full range of relative path inputs so the fix is robust.
        """
        from kanon_cli.commands.repo import resolve_repo_dir

        result = resolve_repo_dir(flag_value=input_path, env={})

        assert os.path.isabs(result), (
            f"resolve_repo_dir({input_path!r}) [{description}] returned relative path {result!r}; expected absolute"
        )

    def test_returned_path_ends_with_expected_basename(self) -> None:
        """The absolute path returned for the default must end with '.repo'.

        Sanity-checks that abspath conversion preserves the path semantics and
        the returned path is rooted at cwd (since '.repo' is relative to cwd).
        """
        from kanon_cli.commands.repo import resolve_repo_dir

        result = resolve_repo_dir(flag_value=None, env={})
        expected = os.path.join(os.getcwd(), ".repo")

        assert result == expected, f"resolve_repo_dir() for default returned {result!r}; expected {expected!r}"
