"""Remote URL scheme classification and HTTPS enforcement policy.

Implements the spec Section 4.7 '<remote> non-HTTPS URL' rule and Section 3.6
trust-model requirement: remote URLs used in manifest resolution must use HTTPS
or SSH. Plain HTTP, file://, and other schemes are rejected by default unless
KANON_ALLOW_INSECURE_REMOTES=1 is set.

Public API:
    RemoteUrlScheme        -- enum of recognized URL scheme categories.
    InsecureRemoteUrlError -- raised when a non-HTTPS/SSH URL is encountered.
    _classify_remote_url_scheme -- classify a URL into a RemoteUrlScheme value.
    _enforce_remote_url_policy  -- raise InsecureRemoteUrlError for disallowed schemes.
"""

from __future__ import annotations

import enum

from kanon_cli.constants import KANON_ALLOW_INSECURE_REMOTES
from kanon_cli.core.include_walker import InstallError


class RemoteUrlScheme(enum.Enum):
    """Enumeration of recognized remote URL scheme categories.

    Values:
        HTTPS:        URL begins with https:// (case-insensitive).
        SSH_GIT_AT:   SCP-style shorthand, e.g. git@host:org/repo.git.
        SSH_PROTOCOL: Explicit ssh:// URL scheme.
        HTTP:         URL begins with http:// (insecure by default).
        FILE:         URL begins with file:// (insecure by default).
        OTHER:        Any other scheme (git://, ftp://, empty, etc.) -- insecure by default.
    """

    HTTPS = "https"
    SSH_GIT_AT = "ssh-git-at"
    SSH_PROTOCOL = "ssh-protocol"
    HTTP = "http"
    FILE = "file"
    OTHER = "other"


class InsecureRemoteUrlError(InstallError):
    """Raised when a <remote> URL does not use an allowed scheme.

    Allowed schemes are HTTPS and SSH (both SCP-style and ssh:// protocol).
    All other schemes (HTTP, file://, git://, empty, etc.) are rejected
    by default and require KANON_ALLOW_INSECURE_REMOTES=1 to bypass.

    Args:
        url: The offending URL string.
        source_path: Identifier of the manifest source that declared this remote
            (typically '<source-name>/<xml-path>').
        remote_name: The <remote> element's name attribute in the manifest XML,
            or an empty string when no name is available.
    """

    def __init__(
        self,
        url: str,
        source_path: str = "",
        remote_name: str = "",
    ) -> None:
        self.url = url
        self.source_path = source_path
        self.remote_name = remote_name
        super().__init__(str(self))

    def __str__(self) -> str:
        lines = [
            "ERROR: Insecure <remote> URL detected in resolved manifest.",
        ]
        if self.source_path:
            lines.append(f"  Source  : {self.source_path}")
        if self.remote_name:
            lines.append(f"  Remote  : {self.remote_name}")
        lines.append(f"  URL     : {self.url}")
        lines.append(
            "  Remediation: Use an HTTPS or SSH <remote> URL, or set\n"
            f"  {KANON_ALLOW_INSECURE_REMOTES}=1 if this is intentional\n"
            "  (the override disables the security check)."
        )
        return "\n".join(lines)


def _classify_remote_url_scheme(url: str) -> RemoteUrlScheme:
    """Classify a remote URL string into a RemoteUrlScheme enum value.

    Matching is case-insensitive for the scheme portion. The SCP-style
    git@ shorthand does not have an explicit scheme separator and is
    detected by the 'git@' prefix.

    Args:
        url: The remote URL string to classify. May be empty.

    Returns:
        The RemoteUrlScheme that best matches the URL's scheme.
        Returns RemoteUrlScheme.OTHER for empty strings and unrecognized schemes.
    """
    lower = url.lower()

    if lower.startswith("https://"):
        return RemoteUrlScheme.HTTPS

    if lower.startswith("ssh://"):
        return RemoteUrlScheme.SSH_PROTOCOL

    if lower.startswith("git@"):
        return RemoteUrlScheme.SSH_GIT_AT

    if lower.startswith("http://"):
        return RemoteUrlScheme.HTTP

    if lower.startswith("file://"):
        return RemoteUrlScheme.FILE

    return RemoteUrlScheme.OTHER


def _enforce_remote_url_policy(
    url: str,
    allow_insecure: bool,
    remote_name: str = "",
    source_path: str = "",
) -> None:
    """Raise InsecureRemoteUrlError when the URL scheme is not HTTPS or SSH.

    HTTPS and SSH URLs (both SCP-style git@ and ssh:// protocol) are always
    accepted. HTTP, file://, and all other schemes are rejected when
    allow_insecure is False.

    Args:
        url: The remote URL to validate.
        allow_insecure: When True, all schemes are accepted without error.
            This corresponds to KANON_ALLOW_INSECURE_REMOTES=1 in the environment.
        remote_name: The <remote> name attribute for error context (optional).
        source_path: The source path identifier for error context (optional).

    Returns:
        None when the URL is accepted.

    Raises:
        InsecureRemoteUrlError: When the URL scheme is not HTTPS/SSH and
            allow_insecure is False.
    """
    scheme = _classify_remote_url_scheme(url)

    if scheme in (RemoteUrlScheme.HTTPS, RemoteUrlScheme.SSH_GIT_AT, RemoteUrlScheme.SSH_PROTOCOL):
        return None

    if allow_insecure:
        return None

    raise InsecureRemoteUrlError(
        url=url,
        source_path=source_path,
        remote_name=remote_name,
    )
