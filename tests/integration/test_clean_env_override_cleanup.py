"""Integration tests for clean-after-env-override-install (GAP-3 / AC-6, AC-8, AC-13, AC-14).

Covers:
  - AC-6 / AC-13: kanon clean removes a marketplace plugin that was registered via
    KANON_MARKETPLACE_INSTALL=true env override even when .kanon stores false.
  - AC-8: kanon clean falls back to .kanon-flag behavior when the lockfile lacks
    marketplace_registered (back-compat with old lockfiles; no crash).
  - AC-14: kanon clean --help snapshot is unchanged (no new flags/args).

All tests operate via internal Python APIs (install(), clean()) to avoid the
subprocess overhead of the real CLI binary, but exercise the real logic end-to-end.
"""

from __future__ import annotations

import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.core.clean import clean
from kanon_cli.core.install import install
from kanon_cli.core.lockfile import read_lockfile


def _write_kanonenv(
    directory: pathlib.Path,
    marketplace_install: bool,
    marketplace_dir: pathlib.Path | None = None,
) -> pathlib.Path:
    """Write a minimal valid .kanon file and return its path.

    Args:
        directory: Directory in which to create the .kanon file.
        marketplace_install: When True, the primary dependency opts into the
            marketplace via the per-dependency KANON_SOURCE_primary_MARKETPLACE
            flag (the 3.0.0 replacement for the removed global
            KANON_MARKETPLACE_INSTALL header).
        marketplace_dir: Path for CLAUDE_MARKETPLACES_DIR, or None to omit.

    Returns:
        Absolute path to the written .kanon file.
    """
    lines = [
        "KANON_SOURCE_primary_URL=https://example.com/primary.git",
        "KANON_SOURCE_primary_REF=main",
        "KANON_SOURCE_primary_PATH=meta.xml",
        "KANON_SOURCE_primary_NAME=primary",
        "KANON_SOURCE_primary_GITBASE=https://example.com",
    ]
    if marketplace_install:
        lines.append("KANON_SOURCE_primary_MARKETPLACE=true")
    if marketplace_dir is not None:
        lines.append(f"CLAUDE_MARKETPLACES_DIR={marketplace_dir}")
    kanonenv = directory / ".kanon"
    kanonenv.write_text("\n".join(lines) + "\n")
    return kanonenv.resolve()


_FAKE_SHA40 = "a" * 40
_FAKE_RESOLVED_REF = "refs/heads/main"


@pytest.mark.integration
class TestCleanEnvOverrideRemovesPlugin:
    """AC-6 / AC-13: clean removes a marketplace registered by env override."""

    def test_clean_removes_marketplace_registered_by_env_override(self, tmp_path: pathlib.Path) -> None:
        """After env-override install writes marketplace_registered=true to lockfile,
        clean must uninstall the marketplace even though .kanon stores
        KANON_MARKETPLACE_INSTALL=false.

        Scenario:
          1. .kanon has KANON_MARKETPLACE_INSTALL=false.
          2. install() is called with KANON_MARKETPLACE_INSTALL=true in env
             (simulated via the marketplace_install override in .kanon for install).
          3. clean() reads the lockfile and finds marketplace_registered=true,
             so it uninstalls the marketplace regardless of the .kanon flag.
        """
        from kanon_cli.core.install import _RefResolution
        from kanon_cli.core.include_walker import IncludeTree

        mp_dir = tmp_path / ".claude-mp"
        mp_dir.mkdir()

        kanonenv_install = _write_kanonenv(tmp_path, marketplace_install=True, marketplace_dir=mp_dir)

        fake_resolution = _RefResolution(sha=_FAKE_SHA40, resolved_ref=_FAKE_RESOLVED_REF)

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install.install_marketplace_plugins"),
            patch("kanon_cli.core.install.register_direct_checkout_marketplaces"),
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=fake_resolution),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("meta.xml"))),
        ):
            install(
                kanonenv_install,
                lock_file_path=tmp_path / ".kanon.lock",
            )

        lf = read_lockfile(tmp_path / ".kanon.lock")
        assert lf.marketplace_registered is True, (
            "install with KANON_MARKETPLACE_INSTALL=true must write marketplace_registered=true to lockfile"
        )
        assert lf.marketplace_dir == str(mp_dir), "install must write the marketplace_dir path to the lockfile"

        kanonenv_clean = _write_kanonenv(tmp_path, marketplace_install=False, marketplace_dir=mp_dir)

        uninstall_calls: list = []

        def fake_uninstall(d: pathlib.Path) -> None:
            uninstall_calls.append(d)

        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins", side_effect=fake_uninstall):
            clean(kanonenv_clean)

        assert len(uninstall_calls) == 1, (
            "clean must call uninstall_marketplace_plugins once when lockfile records marketplace_registered=true, "
            f"even though .kanon stores KANON_MARKETPLACE_INSTALL=false; got {uninstall_calls!r}"
        )
        assert uninstall_calls[0] == mp_dir, (
            f"uninstall must be called with marketplace_dir={mp_dir!r}, got {uninstall_calls[0]!r}"
        )

    def test_install_no_marketplace_writes_false_to_lockfile(self, tmp_path: pathlib.Path) -> None:
        """AC-7: install with KANON_MARKETPLACE_INSTALL=false writes marketplace_registered=false."""
        from kanon_cli.core.install import _RefResolution
        from kanon_cli.core.include_walker import IncludeTree

        kanonenv = _write_kanonenv(tmp_path, marketplace_install=False)

        fake_resolution = _RefResolution(sha=_FAKE_SHA40, resolved_ref=_FAKE_RESOLVED_REF)

        with (
            patch("kanon_cli.repo.repo_init"),
            patch("kanon_cli.repo.repo_envsubst"),
            patch("kanon_cli.repo.repo_sync"),
            patch("kanon_cli.core.install._resolve_ref_to_sha", return_value=fake_resolution),
            patch("kanon_cli.core.install._walk_includes", return_value=IncludeTree(path=pathlib.Path("meta.xml"))),
        ):
            install(
                kanonenv,
                lock_file_path=tmp_path / ".kanon.lock",
            )

        lf = read_lockfile(tmp_path / ".kanon.lock")
        assert lf.marketplace_registered is False, (
            "install with KANON_MARKETPLACE_INSTALL=false must write marketplace_registered=false to lockfile"
        )


@pytest.mark.integration
class TestCleanBackCompatOldLockfile:
    """AC-8: clean falls back to .kanon-flag behavior for old lockfiles."""

    def test_clean_with_no_lockfile_uses_kanon_flag_true(self, tmp_path: pathlib.Path) -> None:
        """When no lockfile exists, clean falls back to .kanon KANON_MARKETPLACE_INSTALL=true."""
        mp_dir = tmp_path / ".claude-mp"
        mp_dir.mkdir()

        kanonenv = _write_kanonenv(tmp_path, marketplace_install=True, marketplace_dir=mp_dir)

        uninstall_calls: list = []

        def fake_uninstall(d: pathlib.Path) -> None:
            uninstall_calls.append(d)

        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins", side_effect=fake_uninstall):
            clean(kanonenv)

        assert len(uninstall_calls) == 1, (
            "clean with no lockfile and KANON_MARKETPLACE_INSTALL=true must still call uninstall"
        )

    def test_clean_with_lockfile_missing_marketplace_field_falls_back_to_kanon_flag(
        self, tmp_path: pathlib.Path
    ) -> None:
        """AC-8: a v4 lockfile that omits marketplace_registered falls back to .kanon flag (no crash)."""
        mp_dir = tmp_path / ".claude-mp"
        mp_dir.mkdir()

        old_lockfile = tmp_path / ".kanon.lock"
        old_lockfile.write_text(
            "schema_version = 4\n"
            'generated_at = "2025-01-01T00:00:00Z"\n'
            'generator = "kanon-cli/2.0.0"\n'
            f'kanon_hash = "sha256:{"a" * 64}"\n'
            "\n"
            "[[sources]]\n"
            'alias = "primary"\n'
            'name = "primary"\n'
            'url = "https://example.com/primary.git"\n'
            'ref_spec = "main"\n'
            'resolved_ref = "refs/heads/main"\n'
            f'resolved_sha = "{"a" * 40}"\n'
            'path = "meta.xml"\n'
        )

        kanonenv = _write_kanonenv(tmp_path, marketplace_install=True, marketplace_dir=mp_dir)

        uninstall_calls: list = []

        def fake_uninstall(d: pathlib.Path) -> None:
            uninstall_calls.append(d)

        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins", side_effect=fake_uninstall):
            clean(kanonenv)

        assert len(uninstall_calls) == 1, (
            "clean with a lockfile that omits marketplace_registered and KANON_MARKETPLACE_INSTALL=true "
            "must fall back to .kanon flag and call uninstall"
        )

    def test_clean_with_lockfile_and_kanon_flag_false_skips_uninstall(self, tmp_path: pathlib.Path) -> None:
        """AC-8: lockfile omitting marketplace_registered + .kanon KANON_MARKETPLACE_INSTALL=false => no uninstall."""

        old_lockfile = tmp_path / ".kanon.lock"
        old_lockfile.write_text(
            "schema_version = 4\n"
            'generated_at = "2025-01-01T00:00:00Z"\n'
            'generator = "kanon-cli/2.0.0"\n'
            f'kanon_hash = "sha256:{"a" * 64}"\n'
            "\n"
            "[[sources]]\n"
            'alias = "primary"\n'
            'name = "primary"\n'
            'url = "https://example.com/primary.git"\n'
            'ref_spec = "main"\n'
            'resolved_ref = "refs/heads/main"\n'
            f'resolved_sha = "{"a" * 40}"\n'
            'path = "meta.xml"\n'
        )

        kanonenv = _write_kanonenv(tmp_path, marketplace_install=False)

        uninstall_calls: list = []

        def fake_uninstall(d: pathlib.Path) -> None:
            uninstall_calls.append(d)

        with patch("kanon_cli.core.clean.uninstall_marketplace_plugins", side_effect=fake_uninstall):
            clean(kanonenv)

        assert len(uninstall_calls) == 0, (
            "clean with a lockfile that omits marketplace_registered and KANON_MARKETPLACE_INSTALL=false "
            "must skip uninstall"
        )


@pytest.mark.integration
class TestCleanHelpUnchanged:
    """AC-14: kanon clean --help must not gain new flags or arguments."""

    def test_clean_help_lists_no_extra_flags(self) -> None:
        """AC-14: the clean command help output is unchanged (no new flags/args added)."""
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "kanon_cli", "clean", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, f"kanon clean --help exited {result.returncode}: {result.stderr}"

        help_text = result.stdout + result.stderr
        assert "--marketplace" not in help_text, "kanon clean --help must not advertise new --marketplace flags"
        assert "--lockfile" not in help_text, "kanon clean --help must not advertise new --lockfile flags"

        assert "clean" in help_text.lower(), "kanon clean --help must include 'clean' in output"
