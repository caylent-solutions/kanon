"""Tests for the kanonenv parser module."""

import os
import pathlib
import stat
import sys
import types

import pytest

from kanon_cli.core import kanonenv as kanonenv_module
from kanon_cli.core.kanonenv import (
    _check_windows_acl,
    _check_write_permission,
    _evaluate_acl_write_principals,
    parse_kanonenv,
    validate_sources,
)


def _block(
    alias: str,
    *,
    url: str = "https://example.com",
    ref: str = "main",
    path: str = "meta.xml",
    name: str | None = None,
    gitbase: str = "https://example.com",
) -> str:
    """Render a complete alias-keyed .kanon source block (spec Section 5.1).

    Every required suffix (_URL, _REF, _PATH, _NAME, _GITBASE) is emitted so the
    block parses. ``name`` defaults to the alias when not given.
    """
    manifest_name = alias if name is None else name
    return (
        f"KANON_SOURCE_{alias}_URL={url}\n"
        f"KANON_SOURCE_{alias}_REF={ref}\n"
        f"KANON_SOURCE_{alias}_PATH={path}\n"
        f"KANON_SOURCE_{alias}_NAME={manifest_name}\n"
        f"KANON_SOURCE_{alias}_GITBASE={gitbase}\n"
    )


@pytest.mark.unit
class TestValidParsing:
    """Verify valid .kanon parsing."""

    def test_parses_kanon_sources(self, tmp_path: pathlib.Path) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(_block("build") + _block("marketplaces", path="mp.xml"))
        result = parse_kanonenv(kanonenv)
        assert result["KANON_SOURCES"] == ["build", "marketplaces"]
        assert "build" in result["sources"]
        assert "marketplaces" in result["sources"]

    def test_surfaces_ref_name_gitbase_keys(self, tmp_path: pathlib.Path) -> None:
        """Each parsed source dict surfaces ref / name / gitbase (no 'revision')."""
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            _block(
                "build",
                url="https://example.com/org/build.git",
                ref=">=1.0.0,<2.0.0",
                path="repo-specs/build.xml",
                name="build-manifest",
                gitbase="https://example.com/org",
            )
        )
        result = parse_kanonenv(kanonenv)
        source = result["sources"]["build"]
        assert source["url"] == "https://example.com/org/build.git"
        assert source["ref"] == ">=1.0.0,<2.0.0"
        assert source["path"] == "repo-specs/build.xml"
        assert source["name"] == "build-manifest"
        assert source["gitbase"] == "https://example.com/org"
        assert "revision" not in source

    def test_parses_globals(self, tmp_path: pathlib.Path) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text("REPO_URL=https://example.com\nREPO_REV=v2.0.0\n" + _block("build"))
        result = parse_kanonenv(kanonenv)
        assert result["globals"]["REPO_URL"] == "https://example.com"
        assert result["globals"]["REPO_REV"] == "v2.0.0"

    def test_parses_marketplace_bool(self, tmp_path: pathlib.Path) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text("KANON_MARKETPLACE_INSTALL=true\n" + _block("build"))
        result = parse_kanonenv(kanonenv)
        assert result["KANON_MARKETPLACE_INSTALL"] is True


@pytest.mark.unit
class TestShellExpansion:
    """Verify ${VAR} expansion."""

    def test_expands_home(self, tmp_path: pathlib.Path) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text("CLAUDE_DIR=${HOME}/.claude\n" + _block("build"))
        result = parse_kanonenv(kanonenv)
        assert result["globals"]["CLAUDE_DIR"] == f"{os.environ['HOME']}/.claude"

    def test_undefined_var_raises(self, tmp_path: pathlib.Path) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text("BAD=${UNDEFINED_XYZ_12345}\n" + _block("build"))
        with pytest.raises(ValueError, match="UNDEFINED_XYZ_12345"):
            parse_kanonenv(kanonenv)


@pytest.mark.unit
class TestEnvOverrides:
    """Verify environment variable overrides."""

    def test_env_overrides_file(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text("REPO_REV=v1.0.0\n" + _block("build"))
        monkeypatch.setenv("REPO_REV", "override")
        result = parse_kanonenv(kanonenv)
        assert result["globals"]["REPO_REV"] == "override"


@pytest.mark.unit
class TestValidation:
    """Verify validation errors."""

    def test_missing_file_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            parse_kanonenv(pathlib.Path("/nonexistent/.kanon"))

    def test_missing_sources_raises(self, tmp_path: pathlib.Path) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text("REPO_URL=https://example.com\n")
        with pytest.raises(ValueError, match="No sources found"):
            parse_kanonenv(kanonenv)

    def test_missing_source_var_raises(self, tmp_path: pathlib.Path) -> None:
        """A URL-only source is partial: discovery names the missing required key."""
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            "KANON_SOURCE_build_URL=https://example.com\n"
            "KANON_SOURCE_build_REF=main\n"
            "KANON_SOURCE_build_PATH=meta.xml\n"
            "KANON_SOURCE_build_GITBASE=https://example.com\n"
        )
        # _NAME is absent -> validate_sources names it.
        with pytest.raises(ValueError, match="KANON_SOURCE_build_NAME"):
            parse_kanonenv(kanonenv)

    def test_partial_source_without_url_raises(self, tmp_path: pathlib.Path) -> None:
        """A non-URL suffix without a URL names the exact missing URL var."""
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text("KANON_SOURCE_build_REF=main\n")
        with pytest.raises(ValueError, match="KANON_SOURCE_build_URL is required but not set"):
            parse_kanonenv(kanonenv)

    def test_validate_sources_direct(self) -> None:
        expanded = {
            "KANON_SOURCE_test_URL": "https://example.com",
            "KANON_SOURCE_test_REF": "main",
            "KANON_SOURCE_test_PATH": "meta.xml",
            "KANON_SOURCE_test_NAME": "test",
            "KANON_SOURCE_test_GITBASE": "https://example.com",
        }
        validate_sources(expanded, ["test"])

    def test_validate_sources_missing(self) -> None:
        expanded = {"KANON_SOURCE_test_URL": "https://example.com"}
        with pytest.raises(ValueError, match="KANON_SOURCE_test_REF"):
            validate_sources(expanded, ["test"])


@pytest.mark.unit
class TestEdgeCases:
    """Verify edge case handling."""

    def test_comments_ignored(self, tmp_path: pathlib.Path) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text("# A comment\n" + _block("build"))
        result = parse_kanonenv(kanonenv)
        for key in result.get("globals", {}):
            assert not key.startswith("#")

    def test_value_with_equals(self, tmp_path: pathlib.Path) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(_block("build", url="https://example.com?a=1"))
        result = parse_kanonenv(kanonenv)
        assert result["sources"]["build"]["url"] == "https://example.com?a=1"

    def test_kanon_sources_present_raises_error(self, tmp_path: pathlib.Path) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text("KANON_SOURCES=build\n" + _block("build"))
        with pytest.raises(ValueError, match="no longer supported"):
            parse_kanonenv(kanonenv)

    def test_auto_discovery_alphabetical_order(self, tmp_path: pathlib.Path) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(
            _block("beta", url="https://example.com/beta.git") + _block("alpha", url="https://example.com/alpha.git")
        )
        result = parse_kanonenv(kanonenv)
        assert result["KANON_SOURCES"] == ["alpha", "beta"]

    def test_marketplace_defaults_false(self, tmp_path: pathlib.Path) -> None:
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(_block("build"))
        result = parse_kanonenv(kanonenv)
        assert result["KANON_MARKETPLACE_INSTALL"] is False

    def test_bom_prefixed_file_parses_clean_keys(self, tmp_path: pathlib.Path) -> None:
        """BOM-prefixed .kanon file must parse with no leading U+FEFF on any key."""
        content = _block("build")
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))

        result = parse_kanonenv(kanonenv)

        for key in result["globals"]:
            assert "\ufeff" not in key, f"BOM codepoint found in globals key: {key!r}"
        for key in result["sources"]:
            assert "\ufeff" not in key, f"BOM codepoint found in source name: {key!r}"
        assert result["KANON_SOURCES"] == ["build"]
        assert result["sources"]["build"]["url"] == "https://example.com"

    def test_bom_and_no_bom_produce_equal_mappings(self, tmp_path: pathlib.Path) -> None:
        """Files with and without a UTF-8 BOM must yield identical parsed results."""
        content = _block("alpha", url="https://example.com/alpha.git")
        with_bom = tmp_path / ".kanon_bom"
        with_bom.write_bytes(b"\xef\xbb\xbf" + content.encode("utf-8"))

        without_bom = tmp_path / ".kanon_no_bom"
        without_bom.write_bytes(content.encode("utf-8"))

        result_bom = parse_kanonenv(with_bom)
        result_plain = parse_kanonenv(without_bom)

        assert result_bom == result_plain


# -- Windows ACL-equivalent fakes (stand in for the GetFileSecurity mechanism) --
#
# pywin32 (win32security / ntsecuritycon) is unavailable off Windows, so the
# _check_windows_acl mechanism is exercised on any platform by injecting a fake
# win32security/ntsecuritycon module pair whose objects mimic the real pywin32
# return shapes. The accept/reject decision under test is the real production
# code path; only the OS security-descriptor source is faked.

_FAKE_ACCESS_ALLOWED_ACE_TYPE = 0
_FAKE_ACCESS_DENIED_ACE_TYPE = 1
_FAKE_OWNER_SID = "S-1-5-21-OWNER"
_FAKE_ADMINISTRATORS_SID = "S-1-5-32-544"
_FAKE_OTHER_SID = "S-1-1-0"  # well-known "Everyone" SID, a broader-than-owner grant


class _FakeAcl:
    """Minimal stand-in for a pywin32 ACL object holding a list of ACE tuples."""

    def __init__(self, aces: list[tuple]) -> None:
        self._aces = aces

    def GetAceCount(self) -> int:
        return len(self._aces)

    def GetAce(self, index: int) -> tuple:
        return self._aces[index]


class _FakeSecurityDescriptor:
    """Minimal stand-in for a pywin32 security descriptor."""

    def __init__(self, owner_sid: str, dacl: "_FakeAcl | None") -> None:
        self._owner_sid = owner_sid
        self._dacl = dacl

    def GetSecurityDescriptorOwner(self) -> str:
        return self._owner_sid

    def GetSecurityDescriptorDacl(self) -> "_FakeAcl | None":
        return self._dacl


def _make_fake_win32security(descriptor: _FakeSecurityDescriptor) -> types.ModuleType:
    """Build a fake ``win32security`` module returning *descriptor* from GetFileSecurity."""
    module = types.ModuleType("win32security")
    module.OWNER_SECURITY_INFORMATION = 0x1
    module.DACL_SECURITY_INFORMATION = 0x4
    module.ACCESS_ALLOWED_ACE_TYPE = _FAKE_ACCESS_ALLOWED_ACE_TYPE
    module.WinBuiltinAdministratorsSid = object()
    module.GetFileSecurity = lambda _path, _info: descriptor
    module.CreateWellKnownSid = lambda _kind: _FAKE_ADMINISTRATORS_SID
    module.ConvertSidToStringSid = lambda sid: sid
    return module


def _make_fake_ntsecuritycon() -> types.ModuleType:
    """Build a fake ``ntsecuritycon`` module exposing the write-class right bits."""
    module = types.ModuleType("ntsecuritycon")
    module.FILE_WRITE_DATA = 0x0002
    module.FILE_APPEND_DATA = 0x0004
    module.WRITE_DAC = 0x40000
    module.WRITE_OWNER = 0x80000
    module.FILE_GENERIC_WRITE = 0x120116
    return module


def _allow_ace(access_mask: int, sid: str) -> tuple:
    """Construct an ACCESS_ALLOWED ACE tuple in pywin32's nested shape."""
    return ((_FAKE_ACCESS_ALLOWED_ACE_TYPE, 0), access_mask, sid)


def _deny_ace(access_mask: int, sid: str) -> tuple:
    """Construct an ACCESS_DENIED ACE tuple in pywin32's nested shape."""
    return ((_FAKE_ACCESS_DENIED_ACE_TYPE, 0), access_mask, sid)


@pytest.mark.unit
class TestPosixWritePermission:
    """Verify the POSIX mode-bit branch of the per-OS write-permission control."""

    @pytest.mark.parametrize(
        ("mode_bits", "expected_fragment"),
        [
            (stat.S_IWGRP, "group-writable"),
            (stat.S_IWOTH, "world-writable"),
            (stat.S_IWGRP | stat.S_IWOTH, "group-writable and world-writable"),
        ],
    )
    def test_rejects_group_or_world_writable(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        mode_bits: int,
        expected_fragment: str,
    ) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(_block("build"))
        kanonenv.chmod(stat.S_IRUSR | stat.S_IWUSR | mode_bits)
        with pytest.raises(ValueError, match=expected_fragment):
            _check_write_permission(kanonenv)

    def test_accepts_owner_only_writable(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(_block("build"))
        kanonenv.chmod(stat.S_IRUSR | stat.S_IWUSR)
        # No exception: owner-only write is the only permitted POSIX state.
        _check_write_permission(kanonenv)

    def test_parse_kanonenv_rejects_world_writable_end_to_end(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(sys, "platform", "linux")
        kanonenv = tmp_path / ".kanon"
        kanonenv.write_text(_block("build"))
        kanonenv.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IWOTH)
        with pytest.raises(ValueError, match="insecure permissions"):
            parse_kanonenv(kanonenv)


@pytest.mark.unit
class TestAclWritePrincipalPolicy:
    """Verify the platform-agnostic owner/admin-only ACL write-grant policy."""

    def test_accepts_owner_and_admin_only(self, tmp_path: pathlib.Path) -> None:
        allowed = {_FAKE_OWNER_SID, _FAKE_ADMINISTRATORS_SID}
        # No exception: every write principal is the owner or Administrators.
        _evaluate_acl_write_principals(
            [_FAKE_OWNER_SID, _FAKE_ADMINISTRATORS_SID],
            allowed,
            tmp_path / ".kanon",
        )

    def test_accepts_empty_write_grant(self, tmp_path: pathlib.Path) -> None:
        allowed = {_FAKE_OWNER_SID, _FAKE_ADMINISTRATORS_SID}
        # No write principals at all is trivially compliant.
        _evaluate_acl_write_principals([], allowed, tmp_path / ".kanon")

    def test_rejects_broader_than_owner_admin_grant(self, tmp_path: pathlib.Path) -> None:
        allowed = {_FAKE_OWNER_SID, _FAKE_ADMINISTRATORS_SID}
        with pytest.raises(ValueError, match=_FAKE_OTHER_SID):
            _evaluate_acl_write_principals(
                [_FAKE_OWNER_SID, _FAKE_OTHER_SID],
                allowed,
                tmp_path / ".kanon",
            )

    def test_rejects_names_every_disallowed_principal(self, tmp_path: pathlib.Path) -> None:
        allowed = {_FAKE_OWNER_SID}
        second_other = "S-1-5-11"  # Authenticated Users
        with pytest.raises(ValueError) as exc_info:
            _evaluate_acl_write_principals(
                [_FAKE_OTHER_SID, second_other, _FAKE_OWNER_SID],
                allowed,
                tmp_path / ".kanon",
            )
        message = str(exc_info.value)
        assert _FAKE_OTHER_SID in message
        assert second_other in message


@pytest.mark.unit
class TestWindowsAclMechanism:
    """Verify the Windows ACL-equivalent mechanism reads the DACL and enforces the policy."""

    def _install_fake_win32(
        self,
        monkeypatch: pytest.MonkeyPatch,
        descriptor: _FakeSecurityDescriptor,
    ) -> None:
        monkeypatch.setitem(sys.modules, "win32security", _make_fake_win32security(descriptor))
        monkeypatch.setitem(sys.modules, "ntsecuritycon", _make_fake_ntsecuritycon())

    def test_accepts_dacl_granting_write_to_owner_and_admin_only(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        nt = _make_fake_ntsecuritycon()
        dacl = _FakeAcl(
            [
                _allow_ace(nt.FILE_GENERIC_WRITE, _FAKE_OWNER_SID),
                _allow_ace(nt.FILE_GENERIC_WRITE, _FAKE_ADMINISTRATORS_SID),
            ]
        )
        descriptor = _FakeSecurityDescriptor(_FAKE_OWNER_SID, dacl)
        self._install_fake_win32(monkeypatch, descriptor)
        # No exception: only owner and Administrators hold write access.
        _check_windows_acl(tmp_path / ".kanon")

    def test_rejects_dacl_granting_write_to_everyone(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        nt = _make_fake_ntsecuritycon()
        dacl = _FakeAcl(
            [
                _allow_ace(nt.FILE_GENERIC_WRITE, _FAKE_OWNER_SID),
                _allow_ace(nt.FILE_WRITE_DATA, _FAKE_OTHER_SID),
            ]
        )
        descriptor = _FakeSecurityDescriptor(_FAKE_OWNER_SID, dacl)
        self._install_fake_win32(monkeypatch, descriptor)
        with pytest.raises(ValueError, match=_FAKE_OTHER_SID):
            _check_windows_acl(tmp_path / ".kanon")

    def test_ignores_read_only_ace_for_other_principal(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        nt = _make_fake_ntsecuritycon()
        read_only_mask = 0x1  # FILE_READ_DATA: no write-class bit set.
        dacl = _FakeAcl(
            [
                _allow_ace(nt.FILE_GENERIC_WRITE, _FAKE_OWNER_SID),
                _allow_ace(read_only_mask, _FAKE_OTHER_SID),
            ]
        )
        descriptor = _FakeSecurityDescriptor(_FAKE_OWNER_SID, dacl)
        self._install_fake_win32(monkeypatch, descriptor)
        # No exception: the broader principal is read-only, not a write grant.
        _check_windows_acl(tmp_path / ".kanon")

    def test_ignores_deny_ace_for_other_principal(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        nt = _make_fake_ntsecuritycon()
        dacl = _FakeAcl(
            [
                _allow_ace(nt.FILE_GENERIC_WRITE, _FAKE_OWNER_SID),
                _deny_ace(nt.FILE_GENERIC_WRITE, _FAKE_OTHER_SID),
            ]
        )
        descriptor = _FakeSecurityDescriptor(_FAKE_OWNER_SID, dacl)
        self._install_fake_win32(monkeypatch, descriptor)
        # No exception: a DENY ACE is not a write grant to that principal.
        _check_windows_acl(tmp_path / ".kanon")

    def test_rejects_null_dacl(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        descriptor = _FakeSecurityDescriptor(_FAKE_OWNER_SID, None)
        self._install_fake_win32(monkeypatch, descriptor)
        with pytest.raises(ValueError, match="NULL discretionary ACL"):
            _check_windows_acl(tmp_path / ".kanon")


@pytest.mark.unit
class TestWritePermissionDispatch:
    """Verify the per-OS dispatch selects the ACL path on Windows and is never a no-op."""

    def test_windows_platform_routes_to_acl_check(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[pathlib.Path] = []

        def _record(path: pathlib.Path) -> None:
            calls.append(path)

        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setattr(kanonenv_module, "_check_windows_acl", _record)
        target = tmp_path / ".kanon"
        _check_write_permission(target)
        assert calls == [target], "Windows must route to the ACL-equivalent check, never skip it"

    def test_non_windows_platform_routes_to_posix_check(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        calls: list[pathlib.Path] = []

        def _record(path: pathlib.Path) -> None:
            calls.append(path)

        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(kanonenv_module, "_check_permissions", _record)
        target = tmp_path / ".kanon"
        _check_write_permission(target)
        assert calls == [target], "POSIX must route to the mode-bit check"
