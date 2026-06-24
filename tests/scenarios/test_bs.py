"""BS (Bootstrap) scenarios from `docs/integration-testing.md`.

``kanon bootstrap`` was removed entirely in the 3.0.0 major release. It is no
longer registered or intercepted, so argparse rejects every ``bootstrap``
invocation (any args/flags) as an unknown command: exit code 2 with an
``invalid choice: 'bootstrap'`` usage error on stderr, and no work performed.
The replacements are ``kanon search`` (catalog discovery, formerly
``bootstrap list``) and ``kanon add`` (adding an entry, formerly
``bootstrap <entry>``).

Scenarios automated (every one exits 2 as an unknown command and writes nothing):
- BS-01: ``bootstrap list`` (replaced by ``kanon search``)
- BS-02: ``bootstrap kanon`` (default output dir)
- BS-03: ``bootstrap kanon --output-dir``
- BS-04: ``bootstrap kanon --output-dir`` into a dir with an existing .kanon
- BS-05: ``bootstrap <unknown-package>``
- BS-06: ``bootstrap kanon --output-dir`` onto a blocker file
- BS-07: ``bootstrap kanon --output-dir`` with a missing parent directory
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios.conftest import run_kanon


_ARGPARSE_USAGE_EXIT = 2


def _assert_bootstrap_rejected(result) -> None:
    """Assert a bootstrap invocation was rejected as an unknown command (exit 2)."""
    assert result.returncode == _ARGPARSE_USAGE_EXIT, (
        f"removed 'bootstrap' must exit {_ARGPARSE_USAGE_EXIT} (argparse unknown command), "
        f"got {result.returncode}\nstderr={result.stderr!r}"
    )
    assert "invalid choice: 'bootstrap'" in result.stderr, (
        f"stderr must name 'bootstrap' as an invalid choice: {result.stderr!r}"
    )


@pytest.mark.scenario
class TestBS:
    def test_bs_01_list_bundled_packages(self) -> None:

        _assert_bootstrap_rejected(run_kanon("bootstrap", "list"))

    def test_bs_02_bootstrap_kanon_default_output_dir(self, tmp_path: pathlib.Path) -> None:
        ws = tmp_path / "bs02"
        ws.mkdir()
        result = run_kanon("bootstrap", "kanon", cwd=ws)
        _assert_bootstrap_rejected(result)
        assert not (ws / ".kanon").exists(), ".kanon must NOT be created (bootstrap is rejected before any work)"
        assert not (ws / "kanon-readme.md").exists(), "kanon-readme.md must NOT be created"

    def test_bs_03_bootstrap_kanon_with_output_dir(self, tmp_path: pathlib.Path) -> None:
        output_dir = tmp_path / "bs03-output"
        result = run_kanon("bootstrap", "kanon", "--output-dir", str(output_dir))
        _assert_bootstrap_rejected(result)
        assert not output_dir.exists(), f"output_dir must NOT be created: {output_dir}"

    def test_bs_04_conflict_existing_kanon_file(self, tmp_path: pathlib.Path) -> None:
        existing_dir = tmp_path / "bs04"
        existing_dir.mkdir()
        (existing_dir / ".kanon").write_text("existing\n")
        result = run_kanon("bootstrap", "kanon", "--output-dir", str(existing_dir))
        _assert_bootstrap_rejected(result)

        assert (existing_dir / ".kanon").read_text() == "existing\n"

    def test_bs_05_unknown_package_name(self) -> None:
        _assert_bootstrap_rejected(run_kanon("bootstrap", "nonexistent"))

    def test_bs_06_blocker_file_at_output_path(self, tmp_path: pathlib.Path) -> None:
        blocker = tmp_path / "bs06-blocker"
        blocker.write_text("")
        result = run_kanon("bootstrap", "kanon", "--output-dir", str(blocker))
        _assert_bootstrap_rejected(result)

        assert blocker.is_file()

    def test_bs_07_missing_parent_directory(self, tmp_path: pathlib.Path) -> None:
        missing_parent = tmp_path / "nonexistent-parent" / "child"
        result = run_kanon("bootstrap", "kanon", "--output-dir", str(missing_parent))
        _assert_bootstrap_rejected(result)
        assert not missing_parent.exists(), "no output directory may be created when bootstrap is rejected"
