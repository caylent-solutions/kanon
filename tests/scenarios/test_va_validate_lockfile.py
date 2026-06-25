"""VA (Validate) lockfile scenarios from `docs/integration-testing.md` §12.

`kanon validate lockfile` (new in 3.0.0) runs the same `.kanon` <-> `.kanon.lock`
consistency check `kanon install` performs implicitly (alias uniqueness, alias-set
parity, per-alias ref-spec parity; spec Section 4.5 / FR-24). These scenarios drive
the real `python -m kanon_cli` CLI against on-disk bare git repos served over
`file://` URLs, so no network access is required.

Scenarios automated:
- VA-05: Validate lockfile on a consistent `.kanon` / `.kanon.lock` pair (exit 0).
- VA-06: Validate lockfile reports ref-spec drift (non-zero + remediation line).
"""

from __future__ import annotations

import pathlib

import pytest

from tests.scenarios.conftest import (
    kanon_clean,
    kanon_install,
    make_plain_repo,
    run_kanon,
)


def _build_manifest_fixture(base: pathlib.Path) -> pathlib.Path:
    """Build the single-source manifest fixture shared by both VA lockfile scenarios.

    The content repo holds one package (``pkg-alpha``); the manifest repo declares
    it at ``.packages/pkg-alpha`` from ``repo-specs/alpha-only.xml`` via an included
    ``repo-specs/remote.xml`` pointing at the content-repos directory. Returns the
    bare manifest repo path so callers can derive its ``file://`` URL.
    """
    content_repos = base / "content-repos"
    manifest_repos = base / "manifest-repos"
    content_repos.mkdir(parents=True)
    manifest_repos.mkdir(parents=True)

    make_plain_repo(content_repos, "pkg-alpha", {"README.md": "# pkg-alpha\n"})
    content_repos_url = content_repos.as_uri()

    remote_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        f'  <remote name="local" fetch="{content_repos_url}/" />\n'
        '  <default remote="local" revision="main" sync-j="4" />\n'
        "</manifest>\n"
    )
    alpha_only_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<manifest>\n"
        '  <include name="repo-specs/remote.xml" />\n'
        '  <project name="pkg-alpha" path=".packages/pkg-alpha"'
        ' remote="local" revision="main" />\n'
        "</manifest>\n"
    )

    return make_plain_repo(
        manifest_repos,
        "manifest-primary",
        {
            "repo-specs/remote.xml": remote_xml,
            "repo-specs/alpha-only.xml": alpha_only_xml,
        },
    )


def _write_kanon(target_dir: pathlib.Path, manifest_url: str, ref: str) -> pathlib.Path:
    """Write a single-source ``.kanon`` for the primary manifest at ``ref``.

    Returns the written ``.kanon`` path. The declared revision (``KANON_SOURCE_
    primary_REF``) is the value the consistency check compares against the lock's
    recorded ref-spec, so changing it without re-installing is what produces drift.
    """
    kanon_file = target_dir / ".kanon"
    kanon_file.write_text(
        f"KANON_SOURCE_primary_URL={manifest_url}\n"
        f"KANON_SOURCE_primary_REF={ref}\n"
        "KANON_SOURCE_primary_PATH=repo-specs/alpha-only.xml\n"
        "KANON_SOURCE_primary_NAME=primary\n"
        "KANON_SOURCE_primary_GITBASE=https://example.com\n"
    )
    return kanon_file


@pytest.mark.scenario
class TestVALockfile:
    def test_va_05_validate_lockfile_consistent_pair(self, tmp_path: pathlib.Path) -> None:
        """VA-05: validate lockfile on a freshly installed pair reports consistent, exit 0."""
        manifest_bare = _build_manifest_fixture(tmp_path / "fixtures")
        manifest_url = manifest_bare.as_uri()

        work_dir = tmp_path / "test-va05"
        work_dir.mkdir()
        kanon_file = _write_kanon(work_dir, manifest_url, "main")

        install_result = kanon_install(
            work_dir,
            extra_env={"KANON_CATALOG_SOURCE": f"{manifest_url}@main", "KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert install_result.returncode == 0, (
            f"kanon install exited {install_result.returncode}\n"
            f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )
        assert (work_dir / ".kanon.lock").is_file(), "kanon install did not write .kanon.lock"

        result = run_kanon("validate", "lockfile", str(kanon_file), cwd=work_dir)

        assert result.returncode == 0, (
            f"kanon validate lockfile exited {result.returncode} on a consistent pair\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "consistent" in result.stdout, (
            f"Expected 'consistent' in stdout, got stdout={result.stdout!r} stderr={result.stderr!r}"
        )

        kanon_clean(work_dir)

    def test_va_06_validate_lockfile_reports_ref_spec_drift(self, tmp_path: pathlib.Path) -> None:
        """VA-06: editing the declared ref after install makes validate lockfile report drift."""
        manifest_bare = _build_manifest_fixture(tmp_path / "fixtures")
        manifest_url = manifest_bare.as_uri()

        work_dir = tmp_path / "test-va06"
        work_dir.mkdir()
        kanon_file = _write_kanon(work_dir, manifest_url, "main")

        install_result = kanon_install(
            work_dir,
            extra_env={"KANON_CATALOG_SOURCE": f"{manifest_url}@main", "KANON_ALLOW_INSECURE_REMOTES": "1"},
        )
        assert install_result.returncode == 0, (
            f"kanon install exited {install_result.returncode}\n"
            f"stdout={install_result.stdout!r}\nstderr={install_result.stderr!r}"
        )

        drifted = kanon_file.read_text().replace("_REF=main", "_REF=refs/tags/1.0.0")
        assert "_REF=refs/tags/1.0.0" in drifted, "test fixture failed to introduce ref-spec drift"
        kanon_file.write_text(drifted)

        result = run_kanon("validate", "lockfile", str(kanon_file), cwd=work_dir)

        assert result.returncode != 0, (
            f"kanon validate lockfile exited 0 despite ref-spec drift\n"
            f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
        )
        assert "ref-specs differ" in result.stderr, (
            f"Expected 'ref-specs differ' in stderr, got stderr={result.stderr!r}"
        )
        assert "kanon install" in result.stderr, (
            f"Expected a remediation line naming 'kanon install' in stderr, got stderr={result.stderr!r}"
        )

        kanon_clean(work_dir)
