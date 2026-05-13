"""Unit tests for remote_url module: RemoteUrlScheme classifier and policy enforcer.

AC-FUNC-001 through AC-FUNC-007 coverage:
- HTTPS accepted unconditionally
- SSH git@ accepted unconditionally
- SSH protocol accepted unconditionally
- HTTP rejected by default, allowed with override
- file:// rejected by default, allowed with override
- git:// (OTHER scheme) rejected by default, allowed with override
- Empty string treated as OTHER; rejected by default
"""

import pytest

from kanon_cli.core.remote_url import (
    InsecureRemoteUrlError,
    RemoteUrlScheme,
    _classify_remote_url_scheme,
    _enforce_remote_url_policy,
)


@pytest.mark.unit
class TestClassifyRemoteUrlScheme:
    """Tests for _classify_remote_url_scheme covering all recognized URL forms."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/foo/bar.git",
            "https://gitlab.com/org/repo.git",
            "HTTPS://example.com/foo.git",
        ],
    )
    def test_https_url_classified_as_https(self, url: str) -> None:
        """HTTPS URLs are classified as RemoteUrlScheme.HTTPS (AC-FUNC-001)."""
        assert _classify_remote_url_scheme(url) == RemoteUrlScheme.HTTPS

    @pytest.mark.parametrize(
        "url",
        [
            "git@github.com:foo/bar.git",
            "git@gitlab.com:org/repo.git",
            "git@bitbucket.org:user/project.git",
        ],
    )
    def test_git_at_url_classified_as_ssh_git_at(self, url: str) -> None:
        """SCP-style git@ URLs are classified as RemoteUrlScheme.SSH_GIT_AT (AC-FUNC-002)."""
        assert _classify_remote_url_scheme(url) == RemoteUrlScheme.SSH_GIT_AT

    @pytest.mark.parametrize(
        "url",
        [
            "ssh://git@host/foo/bar.git",
            "ssh://user@example.com:22/repo.git",
            "SSH://git@example.com/repo.git",
        ],
    )
    def test_ssh_protocol_url_classified_as_ssh_protocol(self, url: str) -> None:
        """SSH protocol URLs are classified as RemoteUrlScheme.SSH_PROTOCOL (AC-FUNC-003)."""
        assert _classify_remote_url_scheme(url) == RemoteUrlScheme.SSH_PROTOCOL

    @pytest.mark.parametrize(
        "url",
        [
            "http://example.com/foo.git",
            "http://internal.corp/repo.git",
            "HTTP://example.com/foo.git",
        ],
    )
    def test_http_url_classified_as_http(self, url: str) -> None:
        """HTTP URLs are classified as RemoteUrlScheme.HTTP (AC-FUNC-004)."""
        assert _classify_remote_url_scheme(url) == RemoteUrlScheme.HTTP

    @pytest.mark.parametrize(
        "url",
        [
            "file:///path/to/repo.git",
            "file:///home/user/my-repo",
            "FILE:///path/repo.git",
        ],
    )
    def test_file_url_classified_as_file(self, url: str) -> None:
        """file:// URLs are classified as RemoteUrlScheme.FILE (AC-FUNC-005)."""
        assert _classify_remote_url_scheme(url) == RemoteUrlScheme.FILE

    @pytest.mark.parametrize(
        "url",
        [
            "git://example.com/foo.git",
            "ftp://example.com/repo.git",
            "custom://example.com/repo.git",
            "GIT://example.com/foo.git",
        ],
    )
    def test_other_scheme_classified_as_other(self, url: str) -> None:
        """Unknown/other scheme URLs are classified as RemoteUrlScheme.OTHER (AC-FUNC-006)."""
        assert _classify_remote_url_scheme(url) == RemoteUrlScheme.OTHER

    def test_empty_string_classified_as_other(self) -> None:
        """Empty string is classified as RemoteUrlScheme.OTHER (AC-FUNC-007)."""
        assert _classify_remote_url_scheme("") == RemoteUrlScheme.OTHER


@pytest.mark.unit
class TestEnforceRemoteUrlPolicy:
    """Tests for _enforce_remote_url_policy covering accept/reject combinations."""

    # -- Always-accepted URLs (HTTPS and SSH variants) --

    @pytest.mark.parametrize(
        "allow_insecure",
        [True, False],
    )
    def test_https_accepted_regardless_of_flag(self, allow_insecure: bool) -> None:
        """HTTPS URLs are accepted regardless of the allow_insecure flag (AC-FUNC-001)."""
        result = _enforce_remote_url_policy("https://github.com/foo/bar.git", allow_insecure=allow_insecure)
        assert result is None

    @pytest.mark.parametrize(
        "allow_insecure",
        [True, False],
    )
    def test_ssh_git_at_accepted_regardless_of_flag(self, allow_insecure: bool) -> None:
        """SCP-style git@ URLs are accepted regardless of the flag (AC-FUNC-002)."""
        result = _enforce_remote_url_policy("git@github.com:foo/bar.git", allow_insecure=allow_insecure)
        assert result is None

    @pytest.mark.parametrize(
        "allow_insecure",
        [True, False],
    )
    def test_ssh_protocol_accepted_regardless_of_flag(self, allow_insecure: bool) -> None:
        """SSH protocol URLs are accepted regardless of the flag (AC-FUNC-003)."""
        result = _enforce_remote_url_policy("ssh://git@host/foo/bar.git", allow_insecure=allow_insecure)
        assert result is None

    # -- Conditionally rejected URLs (HTTP, file://, OTHER) --

    def test_http_rejected_by_default(self) -> None:
        """HTTP URL raises InsecureRemoteUrlError when allow_insecure=False (AC-FUNC-004)."""
        with pytest.raises(InsecureRemoteUrlError):
            _enforce_remote_url_policy("http://example.com/foo.git", allow_insecure=False)

    def test_http_allowed_with_override(self) -> None:
        """HTTP URL returns None when allow_insecure=True (AC-FUNC-004)."""
        result = _enforce_remote_url_policy("http://example.com/foo.git", allow_insecure=True)
        assert result is None

    def test_file_rejected_by_default(self) -> None:
        """file:// URL raises InsecureRemoteUrlError when allow_insecure=False (AC-FUNC-005)."""
        with pytest.raises(InsecureRemoteUrlError):
            _enforce_remote_url_policy("file:///path/to/repo.git", allow_insecure=False)

    def test_file_allowed_with_override(self) -> None:
        """file:// URL returns None when allow_insecure=True (AC-FUNC-005)."""
        result = _enforce_remote_url_policy("file:///path/to/repo.git", allow_insecure=True)
        assert result is None

    def test_other_scheme_rejected_by_default(self) -> None:
        """git:// (OTHER) URL raises InsecureRemoteUrlError when allow_insecure=False (AC-FUNC-006)."""
        with pytest.raises(InsecureRemoteUrlError):
            _enforce_remote_url_policy("git://example.com/foo.git", allow_insecure=False)

    def test_other_scheme_allowed_with_override(self) -> None:
        """git:// (OTHER) URL returns None when allow_insecure=True (AC-FUNC-006)."""
        result = _enforce_remote_url_policy("git://example.com/foo.git", allow_insecure=True)
        assert result is None

    def test_empty_string_rejected_by_default(self) -> None:
        """Empty string raises InsecureRemoteUrlError when allow_insecure=False (AC-FUNC-007)."""
        with pytest.raises(InsecureRemoteUrlError):
            _enforce_remote_url_policy("", allow_insecure=False)

    def test_empty_string_allowed_with_override(self) -> None:
        """Empty string returns None when allow_insecure=True (AC-FUNC-007)."""
        result = _enforce_remote_url_policy("", allow_insecure=True)
        assert result is None


@pytest.mark.unit
class TestInsecureRemoteUrlErrorPayload:
    """Tests for the InsecureRemoteUrlError exception payload."""

    def test_error_contains_url(self) -> None:
        """InsecureRemoteUrlError str representation contains the offending URL."""
        with pytest.raises(InsecureRemoteUrlError) as exc_info:
            _enforce_remote_url_policy("http://example.com/foo.git", allow_insecure=False)
        assert "http://example.com/foo.git" in str(exc_info.value)

    def test_error_contains_override_env_var(self) -> None:
        """InsecureRemoteUrlError names the KANON_ALLOW_INSECURE_REMOTES env var."""
        with pytest.raises(InsecureRemoteUrlError) as exc_info:
            _enforce_remote_url_policy("http://example.com/foo.git", allow_insecure=False)
        assert "KANON_ALLOW_INSECURE_REMOTES" in str(exc_info.value)

    def test_error_starts_with_error_prefix(self) -> None:
        """InsecureRemoteUrlError string starts with 'ERROR:' per spec shape."""
        with pytest.raises(InsecureRemoteUrlError) as exc_info:
            _enforce_remote_url_policy("http://example.com/foo.git", allow_insecure=False)
        assert str(exc_info.value).startswith("ERROR:")

    def test_error_mentions_remediation(self) -> None:
        """InsecureRemoteUrlError contains a remediation hint."""
        with pytest.raises(InsecureRemoteUrlError) as exc_info:
            _enforce_remote_url_policy("http://example.com/foo.git", allow_insecure=False)
        error_text = str(exc_info.value)
        assert "HTTPS" in error_text or "SSH" in error_text

    def test_error_is_instance_of_install_error(self) -> None:
        """InsecureRemoteUrlError is a subclass of InstallError."""
        from kanon_cli.core.include_walker import InstallError

        with pytest.raises(InsecureRemoteUrlError) as exc_info:
            _enforce_remote_url_policy("http://example.com/foo.git", allow_insecure=False)
        assert isinstance(exc_info.value, InstallError)

    def test_error_stores_url_attribute(self) -> None:
        """InsecureRemoteUrlError exposes the url attribute."""
        try:
            _enforce_remote_url_policy("http://example.com/foo.git", allow_insecure=False)
        except InsecureRemoteUrlError as exc:
            assert exc.url == "http://example.com/foo.git"

    def test_error_stores_remote_name_attribute(self) -> None:
        """InsecureRemoteUrlError exposes the remote_name attribute."""
        try:
            _enforce_remote_url_policy(
                "http://example.com/foo.git",
                allow_insecure=False,
                remote_name="origin",
                source_path="my-source/manifest.xml",
            )
        except InsecureRemoteUrlError as exc:
            assert exc.remote_name == "origin"

    def test_error_stores_source_path_attribute(self) -> None:
        """InsecureRemoteUrlError exposes the source_path attribute."""
        try:
            _enforce_remote_url_policy(
                "http://example.com/foo.git",
                allow_insecure=False,
                remote_name="origin",
                source_path="my-source/manifest.xml",
            )
        except InsecureRemoteUrlError as exc:
            assert exc.source_path == "my-source/manifest.xml"

    def test_error_string_contains_remote_name_when_provided(self) -> None:
        """InsecureRemoteUrlError string includes remote name when provided."""
        try:
            _enforce_remote_url_policy(
                "http://example.com/foo.git",
                allow_insecure=False,
                remote_name="upstream",
                source_path="my-source/manifest.xml",
            )
        except InsecureRemoteUrlError as exc:
            assert "upstream" in str(exc)

    def test_error_string_contains_source_path_when_provided(self) -> None:
        """InsecureRemoteUrlError string includes source path when provided."""
        try:
            _enforce_remote_url_policy(
                "http://example.com/foo.git",
                allow_insecure=False,
                remote_name="origin",
                source_path="my-source/manifest.xml",
            )
        except InsecureRemoteUrlError as exc:
            assert "my-source/manifest.xml" in str(exc)
