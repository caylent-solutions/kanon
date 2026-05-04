"""ID (Idempotency) scenarios from `docs/integration-testing.md` §10.

Each scenario invokes real `kanon install` / `kanon clean` subprocesses against
on-disk git fixture repos (built via `make_plain_repo`) and asserts the
documented pass criteria for idempotent behaviour.

Scenarios automated:
- ID-01: Double install succeeds
- ID-02: Clean without prior install succeeds
- ID-03: Double clean succeeds
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios.conftest import (
    kanon_clean,
    kanon_install,
    make_plain_repo,
    write_kanonenv,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_fixtures(parent: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """Create a content repo and a manifest repo, returning their bare paths.

    The manifest repo exposes ``repo-specs/alpha-only.xml`` which references the
    content repo as ``pkg-alpha`` under ``.packages/pkg-alpha``.  Both repos are
    bare git repos reachable via ``file://`` URLs so no network access is needed.
    """
    content_repo = make_plain_repo(
        parent,
        "pkg-alpha",
        {"README.md": "# Alpha Package\n"},
    )

    alpha_only_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="origin" fetch="file://{parent}" />\n'
        '  <default remote="origin" revision="main" />\n'
        '  <project name="pkg-alpha.git" path=".packages/pkg-alpha" revision="main" />\n'
        "</manifest>\n"
    )
    manifest_repo = make_plain_repo(
        parent,
        "manifest-primary",
        {"repo-specs/alpha-only.xml": alpha_only_xml},
    )
    return content_repo, manifest_repo


def _write_primary_kanonenv(
    working_dir: pathlib.Path,
    manifest_bare: pathlib.Path,
) -> pathlib.Path:
    """Write a .kanon pointing at ``manifest_bare`` via ``file://``."""
    return write_kanonenv(
        working_dir,
        sources=[
            (
                "primary",
                f"file://{manifest_bare}",
                "main",
                "repo-specs/alpha-only.xml",
            )
        ],
        marketplace_install="false",
    )


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------


@pytest.mark.scenario
class TestID:
    def test_id_01_double_install_succeeds(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """ID-01: Both invocations of kanon install exit 0; symlink exists after second."""
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        working = tmp_path / "workspace"
        working.mkdir()

        _content_repo, manifest_bare = _make_fixtures(fixtures)
        _write_primary_kanonenv(working, manifest_bare)

        first = kanon_install(working)
        assert first.returncode == 0, (
            f"ID-01: first install failed (rc={first.returncode})\nstdout={first.stdout!r}\nstderr={first.stderr!r}"
        )
        assert "kanon install: done" in first.stdout, (
            f"ID-01: first install stdout missing 'kanon install: done': {first.stdout!r}"
        )

        second = kanon_install(working)
        assert second.returncode == 0, (
            f"ID-01: second install failed (rc={second.returncode})\nstdout={second.stdout!r}\nstderr={second.stderr!r}"
        )
        assert "kanon install: done" in second.stdout, (
            f"ID-01: second install stdout missing 'kanon install: done': {second.stdout!r}"
        )

        pkg_alpha_link = working / ".packages" / "pkg-alpha"
        assert pkg_alpha_link.is_symlink(), (
            f"ID-01: .packages/pkg-alpha symlink missing after second install; "
            f".packages/ contents: {sorted(str(p) for p in (working / '.packages').iterdir()) if (working / '.packages').exists() else 'directory absent'!r}"
        )

    def test_id_02_clean_without_prior_install_succeeds(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """ID-02: kanon clean on a fresh directory exits 0 and emits 'kanon clean: done'."""
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        working = tmp_path / "workspace"
        working.mkdir()

        _content_repo, manifest_bare = _make_fixtures(fixtures)
        _write_primary_kanonenv(working, manifest_bare)

        result = kanon_clean(working)
        assert result.returncode == 0, (
            f"ID-02: clean without prior install failed (rc={result.returncode})\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "kanon clean: done" in result.stdout, f"ID-02: stdout missing 'kanon clean: done': {result.stdout!r}"
        assert not (working / ".packages").exists(), (
            "ID-02: .packages/ should not exist after clean on never-installed dir"
        )
        assert not (working / ".kanon-data").exists(), (
            "ID-02: .kanon-data/ should not exist after clean on never-installed dir"
        )

    def test_id_03_double_clean_succeeds(
        self,
        tmp_path: pathlib.Path,
    ) -> None:
        """ID-03: install then two consecutive cleans all exit 0; dirs absent after second clean."""
        fixtures = tmp_path / "fixtures"
        fixtures.mkdir()
        working = tmp_path / "workspace"
        working.mkdir()

        _content_repo, manifest_bare = _make_fixtures(fixtures)
        _write_primary_kanonenv(working, manifest_bare)

        install_result = kanon_install(working)
        assert install_result.returncode == 0, (
            f"ID-03: install failed (rc={install_result.returncode})\n"
            f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )

        first_clean = kanon_clean(working)
        assert first_clean.returncode == 0, (
            f"ID-03: first clean failed (rc={first_clean.returncode})\n"
            f"stdout={first_clean.stdout!r}\nstderr={first_clean.stderr!r}"
        )

        second_clean = kanon_clean(working)
        assert second_clean.returncode == 0, (
            f"ID-03: second clean failed (rc={second_clean.returncode})\n"
            f"stdout={second_clean.stdout!r}\nstderr={second_clean.stderr!r}"
        )
        assert not (working / ".packages").exists(), "ID-03: .packages/ should not exist after second clean"
        assert not (working / ".kanon-data").exists(), "ID-03: .kanon-data/ should not exist after second clean"
