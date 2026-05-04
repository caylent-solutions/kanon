"""Unit tests for _CheckLocalPath rules 6-11.

Covers:
  PATH-006  dot-dot component raises
  PATH-007  .git component raises
  PATH-008  .repo component raises
  PATH-009  trailing slash without dir_ok raises
  PATH-010  path escaping root via .. raises
  PATH-011  absolute path without abs_ok raises
"""

import pytest

from kanon_cli.repo import manifest_xml


# Convenience alias -- keeps every call-site short.
_check = manifest_xml.XmlManifest._CheckLocalPath


# ---------------------------------------------------------------------------
# PATH-006  dot-dot component
# ---------------------------------------------------------------------------


_DOTDOT_CASES = [
    ("dotdot_alone", ".."),
    ("dotdot_at_start", "../foo"),
    ("dotdot_at_end", "foo/.."),
    ("dotdot_in_middle", "foo/../bar"),
    ("multiple_dotdots", "a/../../b"),
]


class TestPath006DotDotComponent:
    """PATH-006: _CheckLocalPath rejects any path containing a '..' component.

    A '..' component allows callers to escape the repository root.  Any path
    whose split components include '..' must be rejected regardless of flags.
    """

    @pytest.mark.parametrize("label,path", _DOTDOT_CASES)
    def test_dotdot_component_rejected(self, label, path):
        """Every path with a '..' component must produce a non-None error."""
        result = _check(path)
        assert result is not None, f"path with '..' component ({label!r}) must be rejected: {path!r}"

    @pytest.mark.parametrize("label,path", _DOTDOT_CASES)
    def test_dotdot_error_message_mentions_bad_component(self, label, path):
        """The error message must mention 'bad component' for clear diagnostics."""
        result = _check(path)
        assert result is not None
        assert "bad component" in result, f"error for {label!r} must mention 'bad component', got {result!r}"

    def test_dotdot_error_names_the_component(self):
        """The error message must include the '..' component name."""
        result = _check("..")
        assert result is not None
        assert ".." in result, f"error must name the '..' component, got {result!r}"

    def test_dotdot_rejected_with_abs_ok(self):
        """'..' is rejected even when abs_ok=True."""
        result = _check("..", abs_ok=True)
        assert result is not None, "'..' must be rejected even with abs_ok=True"

    def test_dotdot_rejected_with_dir_ok(self):
        """'..' is rejected even when dir_ok=True."""
        result = _check("..", dir_ok=True)
        assert result is not None, "'..' must be rejected even with dir_ok=True"


# ---------------------------------------------------------------------------
# PATH-007  .git component
# ---------------------------------------------------------------------------


_GIT_CASES = [
    ("git_alone", ".git"),
    ("git_at_start", ".git/config"),
    ("git_at_end", "foo/.git"),
    ("git_in_middle", "foo/.git/bar"),
]


class TestPath007GitComponent:
    """PATH-007: _CheckLocalPath rejects any path containing a '.git' component.

    '.git' is a reserved directory name used by git.  Allowing it in
    manifest paths would permit overwriting the git metadata directory.
    """

    @pytest.mark.parametrize("label,path", _GIT_CASES)
    def test_git_component_rejected(self, label, path):
        """Every path containing a '.git' component must produce a non-None error."""
        result = _check(path)
        assert result is not None, f"path with '.git' component ({label!r}) must be rejected: {path!r}"

    @pytest.mark.parametrize("label,path", _GIT_CASES)
    def test_git_error_message_mentions_bad_component(self, label, path):
        """The error message must mention 'bad component' for clear diagnostics."""
        result = _check(path)
        assert result is not None
        assert "bad component" in result, f"error for {label!r} must mention 'bad component', got {result!r}"

    def test_git_error_names_the_component(self):
        """The error message must include '.git' so the user knows the exact cause."""
        result = _check(".git")
        assert result is not None
        assert ".git" in result, f"error must name the '.git' component, got {result!r}"

    def test_git_case_insensitive(self):
        """'.GIT' (uppercase) is also rejected because the check is case-insensitive."""
        result = _check(".GIT")
        assert result is not None, "'.GIT' in uppercase must be rejected"
        assert "bad component" in result

    def test_path_without_git_not_rejected_for_this_rule(self):
        """A normal path like 'gitconfig' does not contain a '.git' component."""
        result = _check("gitconfig")
        assert result is None, f"'gitconfig' must not be rejected: {result!r}"


# ---------------------------------------------------------------------------
# PATH-008  .repo component
# ---------------------------------------------------------------------------


_REPO_CASES = [
    ("repo_alone", ".repo"),
    ("repo_at_start", ".repo/manifest"),
    ("repo_at_end", "foo/.repo"),
    ("repo_in_middle", "foo/.repo/bar"),
    ("repo_with_suffix", ".repo-extra"),
    ("repo_with_suffix_nested", "a/.repo_data/b"),
]


class TestPath008RepoComponent:
    """PATH-008: _CheckLocalPath rejects any path containing a '.repo*' component.

    '.repo' (and any component starting with '.repo') is the managed
    metadata directory.  Writing into it from manifest paths must be
    forbidden.
    """

    @pytest.mark.parametrize("label,path", _REPO_CASES)
    def test_repo_component_rejected(self, label, path):
        """Every path containing a '.repo*' component must produce a non-None error."""
        result = _check(path)
        assert result is not None, f"path with '.repo' component ({label!r}) must be rejected: {path!r}"

    @pytest.mark.parametrize("label,path", _REPO_CASES)
    def test_repo_error_message_mentions_bad_component(self, label, path):
        """The error message must mention 'bad component' for clear diagnostics."""
        result = _check(path)
        assert result is not None
        assert "bad component" in result, f"error for {label!r} must mention 'bad component', got {result!r}"

    def test_repo_error_names_the_component(self):
        """The error message must include '.repo' so the user knows the cause."""
        result = _check(".repo")
        assert result is not None
        assert ".repo" in result, f"error must name the '.repo' component, got {result!r}"

    def test_repo_case_insensitive(self):
        """'.REPO' (uppercase) is also rejected because the check is case-insensitive."""
        result = _check(".REPO")
        assert result is not None, "'.REPO' in uppercase must be rejected"
        assert "bad component" in result

    def test_valid_path_with_repo_substring_in_filename(self):
        """A filename like 'myrepo' (no leading dot) is not rejected for this rule."""
        result = _check("myrepo/file.txt")
        assert result is None, f"'myrepo/file.txt' must not be rejected: {result!r}"


# ---------------------------------------------------------------------------
# PATH-009  trailing slash without dir_ok
# ---------------------------------------------------------------------------


_TRAILING_SLASH_CASES = [
    ("single_component", "foo/"),
    ("nested_path", "foo/bar/"),
    ("deeply_nested", "a/b/c/d/"),
]


class TestPath009TrailingSlashWithoutDirOk:
    """PATH-009: _CheckLocalPath rejects a trailing slash when dir_ok is False.

    A trailing slash indicates the path is a directory.  Without dir_ok=True
    the caller does not expect a directory path.
    """

    @pytest.mark.parametrize("label,path", _TRAILING_SLASH_CASES)
    def test_trailing_slash_rejected_by_default(self, label, path):
        """Trailing slash must be rejected when dir_ok is False (the default)."""
        result = _check(path)
        assert result is not None, f"path with trailing slash ({label!r}) must be rejected by default: {path!r}"

    @pytest.mark.parametrize("label,path", _TRAILING_SLASH_CASES)
    def test_trailing_slash_error_message_mentions_dirs(self, label, path):
        """The error message must mention 'dirs' for a consistent diagnostic."""
        result = _check(path)
        assert result is not None
        assert "dirs" in result, f"error for {label!r} must mention 'dirs', got {result!r}"

    @pytest.mark.parametrize("label,path", _TRAILING_SLASH_CASES)
    def test_trailing_slash_accepted_with_dir_ok(self, label, path):
        """Trailing slash must be accepted when dir_ok=True."""
        result = _check(path, dir_ok=True)
        assert result is None, f"path with trailing slash ({label!r}) with dir_ok=True must be accepted, got {result!r}"

    def test_path_without_trailing_slash_not_rejected_for_this_rule(self):
        """A path without a trailing slash does not trigger the dir rejection."""
        result = _check("foo/bar")
        assert result is None, f"'foo/bar' must not be rejected: {result!r}"


# ---------------------------------------------------------------------------
# PATH-010  path escaping root via ..
# ---------------------------------------------------------------------------


_ESCAPE_CASES = [
    ("dotdot_alone", ".."),
    ("escape_two_levels", "../../outside"),
    ("escape_via_middle", "foo/../.."),
    ("escape_nested", "a/b/../../../etc/passwd"),
]


class TestPath010EscapingRootViaDotDot:
    """PATH-010: _CheckLocalPath rejects paths that escape the repository root.

    Any path that attempts to traverse outside the root via '..' must be
    rejected.  Paths containing '..' components are rejected before they can
    reach the normpath check, ensuring the protection is enforced at the
    earliest validation point.
    """

    @pytest.mark.parametrize("label,path", _ESCAPE_CASES)
    def test_escape_path_rejected(self, label, path):
        """Every path that could escape the root must produce a non-None error."""
        result = _check(path)
        assert result is not None, f"path that escapes root ({label!r}) must be rejected: {path!r}"

    @pytest.mark.parametrize("label,path", _ESCAPE_CASES)
    def test_escape_error_is_meaningful(self, label, path):
        """The error message must provide a meaningful diagnostic about the path."""
        result = _check(path)
        assert result is not None
        meaningful = ("bad component" in result) or ("path cannot be outside" in result)
        assert meaningful, (
            f"error for {label!r} must mention 'bad component' or 'path cannot be outside', got {result!r}"
        )

    def test_escape_rejected_with_all_flags(self):
        """Root-escape via '..' is rejected even with all permissive flags enabled."""
        result = _check("../../outside", dir_ok=True, cwd_dot_ok=True, abs_ok=True)
        assert result is not None, "path escaping root must be rejected with all flags enabled"

    def test_absolute_escape_rejected_with_abs_ok(self):
        """An absolute path that resolves outside root is still rejected when abs_ok=True."""
        result = _check("../../outside", abs_ok=True)
        assert result is not None, "escape via '..' must be rejected even with abs_ok=True"

    def test_normpath_escape_detection(self):
        """Verify that a plain '..' path is rejected as an escape attempt."""
        result = _check("..")
        assert result is not None, "'..' alone must be rejected as a root-escape attempt"


# ---------------------------------------------------------------------------
# PATH-011  absolute path without abs_ok
# ---------------------------------------------------------------------------


_ABSOLUTE_PATH_CASES = [
    ("root_only", "/"),
    ("absolute_simple", "/abs/path"),
    ("absolute_nested", "/etc/passwd"),
    ("absolute_leading_slash", "/foo"),
]

# Subset of absolute paths whose rejection message is "path cannot be outside".
# "/" alone is caught earlier by the trailing-slash (dirs) check, so it cannot
# be used to verify the absolute-path message.
_ABSOLUTE_PATH_OUTSIDE_MSG_CASES = [
    ("absolute_simple", "/abs/path"),
    ("absolute_nested", "/etc/passwd"),
    ("absolute_leading_slash", "/foo"),
]


class TestPath011AbsolutePathWithoutAbsOk:
    """PATH-011: _CheckLocalPath rejects absolute paths when abs_ok is False.

    Absolute paths are not meaningful as relative manifest paths.  Without
    abs_ok=True the function must reject any path that os.path.isabs() or a
    leading-'/' check identifies as absolute.
    """

    @pytest.mark.parametrize("label,path", _ABSOLUTE_PATH_CASES)
    def test_absolute_path_rejected_by_default(self, label, path):
        """Absolute path must be rejected when abs_ok is False (the default)."""
        result = _check(path)
        assert result is not None, f"absolute path ({label!r}) must be rejected by default: {path!r}"

    @pytest.mark.parametrize("label,path", _ABSOLUTE_PATH_OUTSIDE_MSG_CASES)
    def test_absolute_path_error_message_mentions_outside(self, label, path):
        """The error message must mention 'path cannot be outside'.

        The bare '/' path is excluded here because it is caught by the
        trailing-slash check first ('dirs not allowed'); only non-slash-ending
        absolute paths reach the absolute-path check.
        """
        result = _check(path)
        assert result is not None
        assert "path cannot be outside" in result, (
            f"error for {label!r} must mention 'path cannot be outside', got {result!r}"
        )

    def test_absolute_path_accepted_with_abs_ok(self):
        """An absolute path must be accepted when abs_ok=True."""
        result = _check("/abs/path", abs_ok=True)
        assert result is None, f"absolute path with abs_ok=True must be accepted, got {result!r}"

    def test_relative_path_not_rejected_for_this_rule(self):
        """A relative path does not trigger the absolute-path rejection."""
        result = _check("relative/path")
        assert result is None, f"relative path must not be rejected: {result!r}"

    def test_absolute_path_with_dotdot_still_rejected_with_abs_ok(self):
        """An absolute path containing '..' is rejected even with abs_ok=True.

        abs_ok bypasses the absolute-path check but not the component check.
        """
        result = _check("/foo/../..", abs_ok=True)
        assert result is not None, "absolute path with '..' must be rejected even with abs_ok=True"
