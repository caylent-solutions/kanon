"""Integration tests for kanonenv.yaml parsing (20 tests).

Exercises the full parse_kanonenv() pipeline -- reading, env override,
shell-variable expansion, source auto-discovery, and validation -- using
real temporary .kanon files.
"""

import os
import pathlib

import pytest

from kanon_cli.core.kanonenv import parse_kanonenv, validate_sources


# ---------------------------------------------------------------------------
# AC-FUNC-002: kanonenv parsing integration tests (20 tests)
# ---------------------------------------------------------------------------


def _write_kanonenv(path: pathlib.Path, content: str) -> pathlib.Path:
    """Write content to a .kanon file at path and return its absolute path."""
    kanonenv = path / ".kanon"
    kanonenv.write_text(content)
    return kanonenv


@pytest.mark.integration
class TestKanonenvParsingSingleSource:
    """Verify single-source .kanon parsing produces correct structure."""

    def test_single_source_parsed(self, tmp_path: pathlib.Path) -> None:
        kanonenv = _write_kanonenv(
            tmp_path,
            "KANON_SOURCE_build_URL=https://example.com/build.git\n"
            "KANON_SOURCE_build_REVISION=main\n"
            "KANON_SOURCE_build_PATH=default.xml\n",
        )
        result = parse_kanonenv(kanonenv)
        assert result["KANON_SOURCES"] == ["build"]
        assert "build" in result["sources"]

    def test_source_url_field_present(self, tmp_path: pathlib.Path) -> None:
        kanonenv = _write_kanonenv(
            tmp_path,
            "KANON_SOURCE_s_URL=https://example.com/s.git\nKANON_SOURCE_s_REVISION=main\nKANON_SOURCE_s_PATH=m.xml\n",
        )
        result = parse_kanonenv(kanonenv)
        assert result["sources"]["s"]["url"] == "https://example.com/s.git"

    def test_source_revision_field_present(self, tmp_path: pathlib.Path) -> None:
        kanonenv = _write_kanonenv(
            tmp_path,
            "KANON_SOURCE_s_URL=https://example.com/s.git\nKANON_SOURCE_s_REVISION=v1.0.0\nKANON_SOURCE_s_PATH=m.xml\n",
        )
        result = parse_kanonenv(kanonenv)
        assert result["sources"]["s"]["revision"] == "v1.0.0"

    def test_source_path_field_present(self, tmp_path: pathlib.Path) -> None:
        kanonenv = _write_kanonenv(
            tmp_path,
            "KANON_SOURCE_s_URL=https://example.com/s.git\n"
            "KANON_SOURCE_s_REVISION=main\n"
            "KANON_SOURCE_s_PATH=repo-specs/manifest.xml\n",
        )
        result = parse_kanonenv(kanonenv)
        assert result["sources"]["s"]["path"] == "repo-specs/manifest.xml"

    def test_marketplace_install_defaults_false(self, tmp_path: pathlib.Path) -> None:
        kanonenv = _write_kanonenv(
            tmp_path,
            "KANON_SOURCE_s_URL=https://example.com/s.git\nKANON_SOURCE_s_REVISION=main\nKANON_SOURCE_s_PATH=m.xml\n",
        )
        result = parse_kanonenv(kanonenv)
        assert result["KANON_MARKETPLACE_INSTALL"] is False

    def test_marketplace_install_true(self, tmp_path: pathlib.Path) -> None:
        kanonenv = _write_kanonenv(
            tmp_path,
            "KANON_MARKETPLACE_INSTALL=true\n"
            "KANON_SOURCE_s_URL=https://example.com/s.git\n"
            "KANON_SOURCE_s_REVISION=main\n"
            "KANON_SOURCE_s_PATH=m.xml\n",
        )
        result = parse_kanonenv(kanonenv)
        assert result["KANON_MARKETPLACE_INSTALL"] is True


@pytest.mark.integration
class TestKanonenvParsingMultiSource:
    """Verify multi-source .kanon parsing and alphabetical ordering."""

    def test_two_sources_discovered(self, tmp_path: pathlib.Path) -> None:
        kanonenv = _write_kanonenv(
            tmp_path,
            "KANON_SOURCE_alpha_URL=https://example.com/a.git\n"
            "KANON_SOURCE_alpha_REVISION=main\n"
            "KANON_SOURCE_alpha_PATH=m.xml\n"
            "KANON_SOURCE_beta_URL=https://example.com/b.git\n"
            "KANON_SOURCE_beta_REVISION=main\n"
            "KANON_SOURCE_beta_PATH=m.xml\n",
        )
        result = parse_kanonenv(kanonenv)
        assert result["KANON_SOURCES"] == ["alpha", "beta"]

    def test_sources_sorted_alphabetically(self, tmp_path: pathlib.Path) -> None:
        kanonenv = _write_kanonenv(
            tmp_path,
            "KANON_SOURCE_zzz_URL=https://example.com/z.git\n"
            "KANON_SOURCE_zzz_REVISION=main\n"
            "KANON_SOURCE_zzz_PATH=m.xml\n"
            "KANON_SOURCE_aaa_URL=https://example.com/a.git\n"
            "KANON_SOURCE_aaa_REVISION=main\n"
            "KANON_SOURCE_aaa_PATH=m.xml\n",
        )
        result = parse_kanonenv(kanonenv)
        assert result["KANON_SOURCES"] == ["aaa", "zzz"]

    def test_globals_extracted_correctly(self, tmp_path: pathlib.Path) -> None:
        kanonenv = _write_kanonenv(
            tmp_path,
            "REPO_REV=v2.0.0\n"
            "GITBASE=https://github.com/\n"
            "KANON_SOURCE_s_URL=https://example.com/s.git\n"
            "KANON_SOURCE_s_REVISION=main\n"
            "KANON_SOURCE_s_PATH=m.xml\n",
        )
        result = parse_kanonenv(kanonenv)
        assert result["globals"]["REPO_REV"] == "v2.0.0"
        assert result["globals"]["GITBASE"] == "https://github.com/"


@pytest.mark.integration
class TestKanonenvParsingShellExpansion:
    """Verify ${VAR} expansion in .kanon values."""

    def test_expands_home_variable(self, tmp_path: pathlib.Path) -> None:
        kanonenv = _write_kanonenv(
            tmp_path,
            "CLAUDE_DIR=${HOME}/.claude\n"
            "KANON_SOURCE_s_URL=https://example.com/s.git\n"
            "KANON_SOURCE_s_REVISION=main\n"
            "KANON_SOURCE_s_PATH=m.xml\n",
        )
        result = parse_kanonenv(kanonenv)
        expected = os.environ.get("HOME", "")
        assert result["globals"]["CLAUDE_DIR"] == f"{expected}/.claude"

    def test_undefined_var_raises_value_error(self, tmp_path: pathlib.Path) -> None:
        kanonenv = _write_kanonenv(
            tmp_path,
            "BAD=${UNDEFINED_KANON_TEST_VAR_XYZ_12345}\n"
            "KANON_SOURCE_s_URL=https://example.com/s.git\n"
            "KANON_SOURCE_s_REVISION=main\n"
            "KANON_SOURCE_s_PATH=m.xml\n",
        )
        with pytest.raises(ValueError, match="UNDEFINED_KANON_TEST_VAR_XYZ_12345"):
            parse_kanonenv(kanonenv)


@pytest.mark.integration
class TestKanonenvParsingEnvOverrides:
    """Verify environment variable overrides take precedence over file values."""

    def test_env_overrides_file_value(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        kanonenv = _write_kanonenv(
            tmp_path,
            "REPO_REV=v1.0.0\n"
            "KANON_SOURCE_s_URL=https://example.com/s.git\n"
            "KANON_SOURCE_s_REVISION=main\n"
            "KANON_SOURCE_s_PATH=m.xml\n",
        )
        monkeypatch.setenv("REPO_REV", "v99.0.0")
        result = parse_kanonenv(kanonenv)
        assert result["globals"]["REPO_REV"] == "v99.0.0"


@pytest.mark.integration
class TestKanonenvParsingValidation:
    """Verify fail-fast validation errors."""

    def test_missing_file_raises_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            parse_kanonenv(pathlib.Path("/nonexistent/.kanon"))

    def test_no_sources_raises_value_error(self, tmp_path: pathlib.Path) -> None:
        kanonenv = _write_kanonenv(tmp_path, "REPO_REV=v1.0.0\n")
        with pytest.raises(ValueError, match="No sources found"):
            parse_kanonenv(kanonenv)

    def test_missing_revision_raises_value_error(self, tmp_path: pathlib.Path) -> None:
        kanonenv = _write_kanonenv(
            tmp_path,
            "KANON_SOURCE_s_URL=https://example.com/s.git\nKANON_SOURCE_s_PATH=m.xml\n",
        )
        with pytest.raises(ValueError, match="KANON_SOURCE_s_REVISION"):
            parse_kanonenv(kanonenv)

    def test_kanon_sources_key_raises_value_error(self, tmp_path: pathlib.Path) -> None:
        kanonenv = _write_kanonenv(
            tmp_path,
            "KANON_SOURCES=build\n"
            "KANON_SOURCE_build_URL=https://example.com/b.git\n"
            "KANON_SOURCE_build_REVISION=main\n"
            "KANON_SOURCE_build_PATH=m.xml\n",
        )
        with pytest.raises(ValueError, match="no longer supported"):
            parse_kanonenv(kanonenv)

    def test_validate_sources_passes_for_complete_source(self) -> None:
        expanded = {
            "KANON_SOURCE_ok_URL": "https://example.com/ok.git",
            "KANON_SOURCE_ok_REVISION": "main",
            "KANON_SOURCE_ok_PATH": "m.xml",
        }
        validate_sources(expanded, ["ok"])

    def test_missing_url_raises_value_error(self, tmp_path: pathlib.Path) -> None:
        kanonenv = _write_kanonenv(
            tmp_path,
            "KANON_SOURCE_s_REVISION=main\nKANON_SOURCE_s_PATH=m.xml\n",
        )
        with pytest.raises(ValueError, match="No sources found"):
            parse_kanonenv(kanonenv)

    def test_missing_path_raises_value_error(self, tmp_path: pathlib.Path) -> None:
        kanonenv = _write_kanonenv(
            tmp_path,
            "KANON_SOURCE_s_URL=https://example.com/s.git\nKANON_SOURCE_s_REVISION=main\n",
        )
        with pytest.raises(ValueError, match="KANON_SOURCE_s_PATH"):
            parse_kanonenv(kanonenv)

    def test_validate_sources_raises_for_missing_path(self) -> None:
        expanded = {
            "KANON_SOURCE_t_URL": "https://example.com/t.git",
            "KANON_SOURCE_t_REVISION": "main",
        }
        with pytest.raises(ValueError, match="KANON_SOURCE_t_PATH"):
            validate_sources(expanded, ["t"])
