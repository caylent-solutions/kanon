"""Tests for the KANON_MIN_VERSION gate (kanon_cli.core.min_version)."""

import pathlib

import pytest

from kanon_cli.constants import KANON_MIN_VERSION_KEY, KANON_UPDATE_UPGRADE_COMMAND
from kanon_cli.core.min_version import KanonVersionTooOldError, enforce_min_version


def _write_kanon(tmp_path: pathlib.Path, body: str) -> pathlib.Path:
    kanon_file = tmp_path / ".kanon"
    kanon_file.write_text(body, encoding="utf-8")
    return kanon_file


@pytest.mark.unit
class TestEnforceMinVersion:
    """Verify the running-version comparison against the declared minimum."""

    @pytest.mark.parametrize(
        ("declared", "running"),
        [
            ("3.4.2", "3.4.2"),
            ("3.4.2", "3.4.3"),
            ("3.4", "3.4.2"),
            ("3.4.2", "4.0.0"),
            ("  3.4.2  ", "3.4.2"),
        ],
    )
    def test_running_at_or_above_minimum_passes(self, tmp_path: pathlib.Path, declared: str, running: str) -> None:
        kanon_file = _write_kanon(tmp_path, f"{KANON_MIN_VERSION_KEY}={declared}\n")
        enforce_min_version(kanon_file, running_version=running)

    @pytest.mark.parametrize(
        ("declared", "running"),
        [
            ("3.4.2", "3.4.1"),
            ("3.5.0", "3.4.9"),
            ("4.0.0", "3.99.99"),
            ("3.4.2", "3.4.2rc1"),
        ],
    )
    def test_running_below_minimum_raises_with_upgrade_command(
        self, tmp_path: pathlib.Path, declared: str, running: str
    ) -> None:
        kanon_file = _write_kanon(tmp_path, f"{KANON_MIN_VERSION_KEY}={declared}\n")
        with pytest.raises(KanonVersionTooOldError) as exc_info:
            enforce_min_version(kanon_file, running_version=running)
        message = str(exc_info.value)
        assert declared in message
        assert running in message
        assert str(kanon_file) in message
        assert KANON_UPDATE_UPGRADE_COMMAND in message

    def test_too_old_error_is_a_value_error(self) -> None:
        """The CLI boundary turns ValueError into a clean ERROR line and exit 1."""
        assert issubclass(KanonVersionTooOldError, ValueError)

    @pytest.mark.parametrize("declared", ["not-a-version", "", "3.4.x", "${KANON_VERSION}", ">=3.4.2"])
    def test_malformed_value_fails_loudly(self, tmp_path: pathlib.Path, declared: str) -> None:
        kanon_file = _write_kanon(tmp_path, f"{KANON_MIN_VERSION_KEY}={declared}\n")
        with pytest.raises(ValueError, match=KANON_MIN_VERSION_KEY) as exc_info:
            enforce_min_version(kanon_file, running_version="99.0.0")
        assert not isinstance(exc_info.value, KanonVersionTooOldError)

    def test_absent_key_is_a_no_op(self, tmp_path: pathlib.Path) -> None:
        kanon_file = _write_kanon(tmp_path, "KANON_SOURCE_a_URL=https://example.com\n")
        enforce_min_version(kanon_file, running_version="0.0.1")

    def test_missing_file_is_a_no_op(self, tmp_path: pathlib.Path) -> None:
        """kanon add may run before a .kanon exists; there is nothing to enforce yet."""
        enforce_min_version(tmp_path / ".kanon", running_version="0.0.1")

    def test_file_with_no_sources_is_still_enforced(self, tmp_path: pathlib.Path) -> None:
        """The gate reads raw lines, so a sourceless .kanon does not hit NoSourcesError first."""
        kanon_file = _write_kanon(tmp_path, f"# header\n\n{KANON_MIN_VERSION_KEY}=9.0.0\n")
        with pytest.raises(KanonVersionTooOldError):
            enforce_min_version(kanon_file, running_version="3.4.2")

    def test_os_env_does_not_override_file_value(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(KANON_MIN_VERSION_KEY, "0.0.0")
        kanon_file = _write_kanon(tmp_path, f"{KANON_MIN_VERSION_KEY}=9.0.0\n")
        with pytest.raises(KanonVersionTooOldError):
            enforce_min_version(kanon_file, running_version="3.4.2")

    def test_os_env_alone_does_not_impose_a_minimum(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(KANON_MIN_VERSION_KEY, "9.0.0")
        kanon_file = _write_kanon(tmp_path, "KANON_SOURCE_a_URL=https://example.com\n")
        enforce_min_version(kanon_file, running_version="3.4.2")

    def test_defaults_to_installed_package_version(self, tmp_path: pathlib.Path) -> None:
        from kanon_cli import __version__

        kanon_file = _write_kanon(tmp_path, f"{KANON_MIN_VERSION_KEY}={__version__}\n")
        enforce_min_version(kanon_file)
