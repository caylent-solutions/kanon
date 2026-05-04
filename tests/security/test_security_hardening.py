"""Security hardening tests for the kanon-cli .kanon parser.

Verifies that common injection and traversal attacks are rejected
at the parse boundary, before any downstream shell or filesystem
operation occurs.

AC-TEST-001: path traversal in .kanon values is rejected
AC-TEST-002: command injection via env var is not executed
AC-TEST-003: command injection via XML attribute is not executed
AC-TEST-004: symlink TOCTOU race is detected or mitigated
AC-TEST-005: world-writable .kanon is rejected
"""

import pathlib
import stat

import pytest

from kanon_cli.core.kanonenv import parse_kanonenv

# Minimal valid .kanon content template. Each test customizes the PATH value
# to exercise the specific attack vector.
_SAFE_URL = "https://example.com/repo.git"
_SAFE_REVISION = "main"
_SAFE_PATH = "manifests/meta.xml"
_SOURCE_NAME = "src"


def _make_kanonenv(tmp_path: pathlib.Path, path_value: str = _SAFE_PATH) -> pathlib.Path:
    """Write a valid .kanon file with the given KANON_SOURCE_src_PATH value."""
    kanonenv = tmp_path / ".kanon"
    kanonenv.write_text(
        f"KANON_SOURCE_{_SOURCE_NAME}_URL={_SAFE_URL}\n"
        f"KANON_SOURCE_{_SOURCE_NAME}_REVISION={_SAFE_REVISION}\n"
        f"KANON_SOURCE_{_SOURCE_NAME}_PATH={path_value}\n"
    )
    return kanonenv


# ---------------------------------------------------------------------------
# AC-TEST-001: path traversal in .kanon values is rejected
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPathTraversalRejected:
    """KANON_SOURCE_<n>_PATH values containing '..' must be rejected."""

    @pytest.mark.parametrize(
        "traversal_path",
        [
            "../../etc/passwd",
            "../secret.xml",
            "manifests/../../etc/shadow",
            "./../outside.xml",
            "a/b/../../../root.xml",
        ],
    )
    def test_path_traversal_raises_value_error(self, tmp_path: pathlib.Path, traversal_path: str) -> None:
        """parse_kanonenv raises ValueError when manifest path contains '..'."""
        kanonenv = _make_kanonenv(tmp_path, traversal_path)
        with pytest.raises(ValueError, match=r"\.\.|path traversal"):
            parse_kanonenv(kanonenv)

    def test_safe_relative_path_is_accepted(self, tmp_path: pathlib.Path) -> None:
        """A manifest path without '..' is accepted without error."""
        kanonenv = _make_kanonenv(tmp_path, "manifests/default.xml")
        result = parse_kanonenv(kanonenv)
        assert result["sources"][_SOURCE_NAME]["path"] == "manifests/default.xml"

    def test_single_dot_path_is_accepted(self, tmp_path: pathlib.Path) -> None:
        """A path starting with a single dot (e.g. './meta.xml') is accepted."""
        kanonenv = _make_kanonenv(tmp_path, "./meta.xml")
        result = parse_kanonenv(kanonenv)
        assert result["sources"][_SOURCE_NAME]["path"] == "./meta.xml"


# ---------------------------------------------------------------------------
# AC-TEST-002: command injection via env var is not executed
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCommandInjectionViaEnvVarNotExecuted:
    """Shell metacharacters supplied through env var overrides must be
    treated as literal strings, not executed by the shell.
    """

    @pytest.mark.parametrize(
        "injection_payload",
        [
            "$(echo injected)",
            "`echo injected`",
            "value; echo injected",
            "value && echo injected",
            "value | cat /etc/passwd",
        ],
    )
    def test_env_var_injection_stored_as_literal(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        injection_payload: str,
    ) -> None:
        """A KANON_SOURCE env var override with shell metacharacters is stored
        as a literal string -- no shell expansion occurs inside parse_kanonenv.
        """
        kanonenv = _make_kanonenv(tmp_path, _SAFE_PATH)
        env_var = f"KANON_SOURCE_{_SOURCE_NAME}_REVISION"
        monkeypatch.setenv(env_var, injection_payload)
        # parse_kanonenv must not raise, and must return the payload verbatim
        result = parse_kanonenv(kanonenv)
        assert result["sources"][_SOURCE_NAME]["revision"] == injection_payload, (
            f"Expected literal payload in revision, got {result['sources'][_SOURCE_NAME]['revision']!r}"
        )

    def test_dollar_sign_in_url_env_var_stored_literally(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A URL containing a dollar sign set via env var is stored as-is."""
        kanonenv = _make_kanonenv(tmp_path, _SAFE_PATH)
        monkeypatch.setenv(f"KANON_SOURCE_{_SOURCE_NAME}_URL", "https://host/$branch")
        result = parse_kanonenv(kanonenv)
        assert result["sources"][_SOURCE_NAME]["url"] == "https://host/$branch"


# ---------------------------------------------------------------------------
# AC-TEST-003: command injection via XML attribute is not executed
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCommandInjectionViaXmlAttributeNotExecuted:
    """XML-special characters in .kanon values must be stored as literal
    strings -- kanon must never evaluate them as markup or shell.
    """

    @pytest.mark.parametrize(
        "xml_payload",
        [
            '<project name="evil" />',
            "&amp; echo injected",
            '"value" onload="alert(1)"',
            "' OR '1'='1",
            "<!-- comment --> echo injected",
        ],
    )
    def test_xml_payload_in_path_stored_as_literal(self, tmp_path: pathlib.Path, xml_payload: str) -> None:
        """XML-special characters in a .kanon value are stored verbatim by the
        parser -- no XML parsing or evaluation is performed on the raw values.
        """
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            f"KANON_SOURCE_{_SOURCE_NAME}_URL={_SAFE_URL}\n"
            f"KANON_SOURCE_{_SOURCE_NAME}_REVISION={_SAFE_REVISION}\n"
            f"KANON_SOURCE_{_SOURCE_NAME}_PATH={xml_payload}\n"
        )
        # The parser reads KEY=VALUE pairs as plain strings -- it does not
        # perform XML interpretation, so the payload is stored verbatim.
        result = parse_kanonenv(kanonenv)
        assert result["sources"][_SOURCE_NAME]["path"] == xml_payload

    def test_url_with_xml_characters_stored_literally(self, tmp_path: pathlib.Path) -> None:
        """A URL containing XML characters is stored verbatim in the config."""
        xml_url = "https://example.com/repo&branch=main"
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            f"KANON_SOURCE_{_SOURCE_NAME}_URL={xml_url}\n"
            f"KANON_SOURCE_{_SOURCE_NAME}_REVISION={_SAFE_REVISION}\n"
            f"KANON_SOURCE_{_SOURCE_NAME}_PATH={_SAFE_PATH}\n"
        )
        result = parse_kanonenv(kanonenv)
        assert result["sources"][_SOURCE_NAME]["url"] == xml_url


# ---------------------------------------------------------------------------
# AC-TEST-004: symlink TOCTOU race is detected or mitigated
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSymlinkToctouMitigated:
    """When .kanon is a symlink pointing outside the project tree,
    parse_kanonenv should raise a ValueError to prevent TOCTOU attacks.
    """

    def test_symlink_to_file_outside_parent_raises(self, tmp_path: pathlib.Path) -> None:
        """A .kanon symlink resolving outside the parent directory raises ValueError."""
        # Create a real .kanon file in a separate temp dir (simulates external path)
        external_dir = tmp_path / "external"
        external_dir.mkdir()
        external_kanon = external_dir / ".kanon"
        external_kanon.write_text(
            f"KANON_SOURCE_{_SOURCE_NAME}_URL={_SAFE_URL}\n"
            f"KANON_SOURCE_{_SOURCE_NAME}_REVISION={_SAFE_REVISION}\n"
            f"KANON_SOURCE_{_SOURCE_NAME}_PATH={_SAFE_PATH}\n"
        )

        project_dir = tmp_path / "project"
        project_dir.mkdir()
        symlink_kanon = project_dir / ".kanon"
        symlink_kanon.symlink_to(external_kanon)

        with pytest.raises(ValueError, match=r"symlink|outside|traversal"):
            parse_kanonenv(symlink_kanon)

    def test_regular_file_kanon_is_accepted(self, tmp_path: pathlib.Path) -> None:
        """A regular (non-symlink) .kanon file is accepted normally."""
        kanonenv = _make_kanonenv(tmp_path)
        assert not kanonenv.is_symlink()
        result = parse_kanonenv(kanonenv)
        assert _SOURCE_NAME in result["sources"]

    def test_symlink_within_same_directory_raises(self, tmp_path: pathlib.Path) -> None:
        """A .kanon symlink that resolves inside the same directory still raises.

        Even an internal symlink introduces TOCTOU risk because the target
        can be replaced between the resolution check and the open call.
        Any symlink is rejected regardless of where it resolves.
        """
        real_file = tmp_path / "actual_kanon"
        real_file.write_text(
            f"KANON_SOURCE_{_SOURCE_NAME}_URL={_SAFE_URL}\n"
            f"KANON_SOURCE_{_SOURCE_NAME}_REVISION={_SAFE_REVISION}\n"
            f"KANON_SOURCE_{_SOURCE_NAME}_PATH={_SAFE_PATH}\n"
        )
        symlink_kanon = tmp_path / ".kanon"
        symlink_kanon.symlink_to(real_file)

        with pytest.raises(ValueError, match=r"symlink|outside|traversal"):
            parse_kanonenv(symlink_kanon)


# ---------------------------------------------------------------------------
# AC-TEST-005: world-writable .kanon is rejected
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestWorldWritableKanonRejected:
    """A .kanon file with world-writable permissions must be rejected to
    prevent privilege escalation and tampering attacks.
    """

    def test_world_writable_file_raises_value_error(self, tmp_path: pathlib.Path) -> None:
        """parse_kanonenv raises ValueError when .kanon is world-writable."""
        kanonenv = _make_kanonenv(tmp_path)
        # Set world-writable (o+w) bit
        current_mode = kanonenv.stat().st_mode
        kanonenv.chmod(current_mode | stat.S_IWOTH)
        with pytest.raises(ValueError, match=r"world.writ|permission|insecure"):
            parse_kanonenv(kanonenv)

    def test_group_writable_file_raises_value_error(self, tmp_path: pathlib.Path) -> None:
        """parse_kanonenv raises ValueError when .kanon is group-writable."""
        kanonenv = _make_kanonenv(tmp_path)
        current_mode = kanonenv.stat().st_mode
        kanonenv.chmod(current_mode | stat.S_IWGRP)
        with pytest.raises(ValueError, match=r"world.writ|group.writ|permission|insecure"):
            parse_kanonenv(kanonenv)

    def test_owner_only_write_is_accepted(self, tmp_path: pathlib.Path) -> None:
        """A .kanon file writable only by the owner (0o600, 0o640, 0o644) is accepted."""
        kanonenv = _make_kanonenv(tmp_path)
        # Explicitly remove group and other write bits
        kanonenv.chmod(0o644)
        result = parse_kanonenv(kanonenv)
        assert _SOURCE_NAME in result["sources"]

    @pytest.mark.parametrize(
        "mode",
        [
            0o777,  # rwxrwxrwx
            0o666,  # rw-rw-rw-
            0o664,  # rw-rw-r-- (group-writable)
            0o606,  # rw----rw- (world-writable)
        ],
    )
    def test_permissive_modes_are_rejected(self, tmp_path: pathlib.Path, mode: int) -> None:
        """Any mode with group or world write bits set must be rejected."""
        kanonenv = _make_kanonenv(tmp_path)
        kanonenv.chmod(mode)
        with pytest.raises(ValueError, match=r"world.writ|group.writ|permission|insecure"):
            parse_kanonenv(kanonenv)

    @pytest.mark.parametrize(
        "mode",
        [
            0o600,  # rw------- (owner read/write only)
            0o644,  # rw-r--r-- (standard read-only for others)
            0o640,  # rw-r----- (owner rw, group r)
        ],
    )
    def test_safe_modes_are_accepted(self, tmp_path: pathlib.Path, mode: int) -> None:
        """Files with safe permission modes (no group/other write) are accepted."""
        kanonenv = _make_kanonenv(tmp_path)
        kanonenv.chmod(mode)
        result = parse_kanonenv(kanonenv)
        assert _SOURCE_NAME in result["sources"]
