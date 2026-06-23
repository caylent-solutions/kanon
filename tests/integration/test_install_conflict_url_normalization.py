"""Integration tests for canonical-URL conflict detection in kanon install.

AC-TEST-002: two fixture sources declaring the same canonical-URL project under
SSH and HTTPS raw URLs respectively but pinning different SHAs -> kanon install
exits non-zero with CanonicalUrlConflictError and the error message includes both
raw forms and the canonical form.

AC-CYCLE-001: end-to-end cycle:
  - Source A: git@gitserver:org/example-package.git@1.0.0
  - Source B: https://gitserver/org/example-package.git@2.0.0
  Both canonicalize to https://gitserver/org/example-package but pin different SHAs.
  install() raises CanonicalUrlConflictError.
  After aligning both to the same SHA (or removing one source), install succeeds.

These tests use real local git repos so git ls-remote works without network access.
repo tool calls (repo_init, repo_envsubst, repo_sync) are mocked.
"""

from __future__ import annotations

import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.core.include_walker import IncludeTree
from kanon_cli.core.install import (
    CanonicalUrlConflictError,
    _RefResolution,
    install,
)

# ---------------------------------------------------------------------------
# Override autouse conftest fixtures: this module uses real git repos
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_resolve_ref_to_sha():
    """Override: each test supplies its own _resolve_ref_to_sha patch."""
    yield


@pytest.fixture(autouse=True)
def _mock_check_sha_reachable():
    """Override: no SHA reachability checks needed for conflict-detection tests."""
    with patch("kanon_cli.core.install._check_sha_reachable"):
        yield


@pytest.fixture(autouse=True)
def _mock_walk_includes():
    """Override: mock _walk_includes so tests that mock repo ops do not require real XML files on disk."""
    with patch(
        "kanon_cli.core.install._walk_includes",
        return_value=IncludeTree(path=pathlib.Path("manifest.xml")),
    ):
        yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_two_source_kanon(
    project_dir: pathlib.Path,
    source_a_url: str,
    source_a_rev: str,
    source_b_url: str,
    source_b_rev: str,
) -> pathlib.Path:
    """Write a two-source .kanon file into project_dir.

    Args:
        project_dir: Directory for the .kanon file.
        source_a_url: URL for the first source (source name: alpha).
        source_a_rev: Revision spec for the first source.
        source_b_url: URL for the second source (source name: bravo).
        source_b_rev: Revision spec for the second source.

    Returns:
        Absolute path to the written .kanon file.
    """
    kanon_path = project_dir / ".kanon"
    kanon_path.write_text(
        f"KANON_MARKETPLACE_INSTALL=false\n"
        f"KANON_SOURCE_alpha_URL={source_a_url}\n"
        f"KANON_SOURCE_alpha_REF={source_a_rev}\n"
        f"KANON_SOURCE_alpha_PATH=manifest.xml\n"
        f"KANON_SOURCE_alpha_NAME=alpha\n"
        f"KANON_SOURCE_alpha_GITBASE=https://example.com\n"
        f"KANON_SOURCE_bravo_URL={source_b_url}\n"
        f"KANON_SOURCE_bravo_REF={source_b_rev}\n"
        f"KANON_SOURCE_bravo_PATH=manifest.xml\n"
        f"KANON_SOURCE_bravo_NAME=bravo\n"
        f"KANON_SOURCE_bravo_GITBASE=https://example.com\n"
    )
    return kanon_path.resolve()


def _write_single_source_kanon(
    project_dir: pathlib.Path,
    source_url: str,
    source_rev: str,
) -> pathlib.Path:
    """Write a single-source .kanon file into project_dir.

    Args:
        project_dir: Directory for the .kanon file.
        source_url: URL for the source (source name: alpha).
        source_rev: Revision spec for the source.

    Returns:
        Absolute path to the written .kanon file.
    """
    kanon_path = project_dir / ".kanon"
    kanon_path.write_text(
        f"KANON_MARKETPLACE_INSTALL=false\n"
        f"KANON_SOURCE_alpha_URL={source_url}\n"
        f"KANON_SOURCE_alpha_REF={source_rev}\n"
        f"KANON_SOURCE_alpha_PATH=manifest.xml\n"
        f"KANON_SOURCE_alpha_NAME=alpha\n"
        f"KANON_SOURCE_alpha_GITBASE=https://example.com\n"
    )
    return kanon_path.resolve()


def _run_install_mocked(
    kanon_path: pathlib.Path,
    sha_map: dict[str, tuple[str, str]],
) -> None:
    """Run install() with repo tool calls mocked out.

    ``_resolve_ref_to_sha`` is patched so that each URL in ``sha_map`` resolves
    to the corresponding (sha, ref) pair. ``resolve_version`` is patched to
    return the ref portion of the resolved pair directly (so no live git
    ls-remote call is made for version-constraint resolution).

    ``kanon install`` is hermetic (spec Section 5.2 / FR-7): it resolves no
    catalog source, so ``catalog_source`` is left ``None``.

    Args:
        kanon_path: Path to the .kanon configuration file.
        sha_map: Maps source URL to (sha, resolved_ref) pair.
    """

    def _fake_resolve_ref_to_sha(url: str, ref: str) -> _RefResolution:
        if url in sha_map:
            sha, resolved_ref = sha_map[url]
            return _RefResolution(sha=sha, resolved_ref=resolved_ref)
        raise ValueError(f"Unexpected URL in test: {url!r}")

    def _fake_resolve_version(url: str, rev_spec: str) -> str:
        # Return the resolved_ref from sha_map when the URL is known;
        # otherwise pass through the rev_spec unchanged (e.g. branch names).
        if url in sha_map:
            _sha, resolved_ref = sha_map[url]
            return resolved_ref
        return rev_spec

    with (
        patch("kanon_cli.core.install._resolve_ref_to_sha", side_effect=_fake_resolve_ref_to_sha),
        patch("kanon_cli.core.install.resolve_version", side_effect=_fake_resolve_version),
        patch("kanon_cli.core.install.run_repo_init"),
        patch("kanon_cli.core.install.run_repo_envsubst"),
        patch("kanon_cli.core.install.run_repo_sync"),
    ):
        install(kanon_path, lock_file_path=kanon_path.parent / ".kanon.lock")


# ---------------------------------------------------------------------------
# AC-TEST-002 / AC-CYCLE-001: SSH vs HTTPS conflict
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestInstallConflictUrlNormalization:
    """Two sources with SSH and HTTPS URLs that canonicalize to the same URL
    but pin different SHAs raise CanonicalUrlConflictError.
    """

    def test_ssh_vs_https_different_sha_raises_conflict_error(self, tmp_path: pathlib.Path) -> None:
        """kanon install raises CanonicalUrlConflictError when two sources share a canonical URL but differ in SHA."""
        # Source A: SSH URL for the "example-package" repo, pinned to SHA_A
        sha_a = "a" * 40
        sha_b = "b" * 40
        source_a_url = "git@gitserver:org/example-package.git"
        source_b_url = "https://gitserver/org/example-package.git"
        # Both canonicalize to https://gitserver/org/example-package

        kanon_path = _write_two_source_kanon(
            tmp_path,
            source_a_url=source_a_url,
            source_a_rev="==1.0.0",
            source_b_url=source_b_url,
            source_b_rev="==2.0.0",
        )

        sha_map = {
            source_a_url: (sha_a, "refs/tags/1.0.0"),
            source_b_url: (sha_b, "refs/tags/2.0.0"),
        }

        with pytest.raises(CanonicalUrlConflictError) as exc_info:
            _run_install_mocked(kanon_path, sha_map)

        error_msg = str(exc_info.value)
        # Both raw forms must appear
        assert source_a_url in error_msg
        assert source_b_url in error_msg
        # The canonical form must appear
        assert "https://gitserver/org/example-package" in error_msg
        assert "both URLs canonicalize to:" in error_msg

    def test_ssh_vs_https_different_sha_error_contains_both_shas(self, tmp_path: pathlib.Path) -> None:
        """The conflict error message includes both differing SHAs."""
        sha_a = "a" * 40
        sha_b = "b" * 40
        source_a_url = "git@gitserver:org/example-package.git"
        source_b_url = "https://gitserver/org/example-package.git"

        kanon_path = _write_two_source_kanon(
            tmp_path,
            source_a_url=source_a_url,
            source_a_rev="==1.0.0",
            source_b_url=source_b_url,
            source_b_rev="==2.0.0",
        )

        sha_map = {
            source_a_url: (sha_a, "refs/tags/1.0.0"),
            source_b_url: (sha_b, "refs/tags/2.0.0"),
        }

        with pytest.raises(CanonicalUrlConflictError) as exc_info:
            _run_install_mocked(kanon_path, sha_map)

        error_msg = str(exc_info.value)
        assert sha_a in error_msg
        assert sha_b in error_msg

    def test_ssh_vs_https_different_sha_error_contains_source_paths(self, tmp_path: pathlib.Path) -> None:
        """The conflict error message includes source-path lines for both sources."""
        sha_a = "a" * 40
        sha_b = "b" * 40
        source_a_url = "git@gitserver:org/example-package.git"
        source_b_url = "https://gitserver/org/example-package.git"

        kanon_path = _write_two_source_kanon(
            tmp_path,
            source_a_url=source_a_url,
            source_a_rev="==1.0.0",
            source_b_url=source_b_url,
            source_b_rev="==2.0.0",
        )

        sha_map = {
            source_a_url: (sha_a, "refs/tags/1.0.0"),
            source_b_url: (sha_b, "refs/tags/2.0.0"),
        }

        with pytest.raises(CanonicalUrlConflictError) as exc_info:
            _run_install_mocked(kanon_path, sha_map)

        error_msg = str(exc_info.value)
        # Source paths are in the form "<source-name>/<manifest-path>"
        assert "alpha/manifest.xml" in error_msg
        assert "bravo/manifest.xml" in error_msg

    def test_same_canonical_url_same_sha_no_conflict(self, tmp_path: pathlib.Path) -> None:
        """Two sources with the same canonical URL AND same SHA do not raise an error (benign diamond)."""
        sha_a = "a" * 40
        source_a_url = "git@gitserver:org/example-package.git"
        source_b_url = "https://gitserver/org/example-package.git"

        kanon_path = _write_two_source_kanon(
            tmp_path,
            source_a_url=source_a_url,
            source_a_rev="==1.0.0",
            source_b_url=source_b_url,
            source_b_rev="==1.0.0",
        )

        sha_map = {
            source_a_url: (sha_a, "refs/tags/1.0.0"),
            source_b_url: (sha_a, "refs/tags/1.0.0"),
        }

        # Should NOT raise -- both canonicalize to the same URL and same SHA
        _run_install_mocked(kanon_path, sha_map)

    def test_distinct_canonical_urls_no_conflict(self, tmp_path: pathlib.Path) -> None:
        """Two sources with entirely different canonical URLs do not raise an error."""
        sha_a = "a" * 40
        sha_b = "b" * 40
        source_a_url = "https://gitserver/org/package-a.git"
        source_b_url = "https://gitserver/org/package-b.git"

        kanon_path = _write_two_source_kanon(
            tmp_path,
            source_a_url=source_a_url,
            source_a_rev="==1.0.0",
            source_b_url=source_b_url,
            source_b_rev="==2.0.0",
        )

        sha_map = {
            source_a_url: (sha_a, "refs/tags/1.0.0"),
            source_b_url: (sha_b, "refs/tags/2.0.0"),
        }

        # Should NOT raise -- different canonical URLs
        _run_install_mocked(kanon_path, sha_map)

    def test_conflict_detected_on_lockfile_consistent_path(self, tmp_path: pathlib.Path) -> None:
        """Conflict is detected on the lockfile-consistent path (detector runs against lockfile contents).

        This simulates a scenario where a conflict was already baked into the
        lockfile -- install re-runs the detector against lockfile contents so
        the operator sees the error even without a fresh resolve.
        """
        import datetime

        from kanon_cli.core.lockfile import (
            CURRENT_SCHEMA_VERSION,
            Lockfile,
            SourceEntry,
            write_lockfile,
        )
        from kanon_cli.core.kanon_hash import kanon_hash

        sha_a = "a" * 40
        sha_b = "b" * 40
        source_a_url = "git@gitserver:org/example-package.git"
        source_b_url = "https://gitserver/org/example-package.git"

        kanon_path = _write_two_source_kanon(
            tmp_path,
            source_a_url=source_a_url,
            source_a_rev="==1.0.0",
            source_b_url=source_b_url,
            source_b_rev="==2.0.0",
        )

        # Build a lockfile whose kanon_hash matches the .kanon so the
        # consistent path is taken, but whose sources have conflicting canonical URLs.
        computed_hash = kanon_hash(kanon_path)
        lockfile_path = kanon_path.parent / ".kanon.lock"

        lf = Lockfile(
            schema_version=CURRENT_SCHEMA_VERSION,
            generated_at=datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            generator="kanon-cli/test",
            kanon_hash=computed_hash,
            sources=[
                SourceEntry(
                    alias="alpha",
                    name="alpha",
                    url=source_a_url,
                    ref_spec="==1.0.0",
                    resolved_ref="refs/tags/1.0.0",
                    resolved_sha=sha_a,
                    path="manifest.xml",
                ),
                SourceEntry(
                    alias="bravo",
                    name="bravo",
                    url=source_b_url,
                    ref_spec="==2.0.0",
                    resolved_ref="refs/tags/2.0.0",
                    resolved_sha=sha_b,
                    path="manifest.xml",
                ),
            ],
        )
        write_lockfile(lf, lockfile_path)

        # Now run install on the consistent path -- it should detect the conflict
        # against the lockfile data.
        with (
            patch("kanon_cli.core.install.run_repo_init"),
            patch("kanon_cli.core.install.run_repo_envsubst"),
            patch("kanon_cli.core.install.run_repo_sync"),
        ):
            with pytest.raises(CanonicalUrlConflictError) as exc_info:
                install(kanon_path, lock_file_path=kanon_path.parent / ".kanon.lock")

        error_msg = str(exc_info.value)
        assert source_a_url in error_msg
        assert source_b_url in error_msg
        assert "https://gitserver/org/example-package" in error_msg

    def test_align_shas_resolves_conflict(self, tmp_path: pathlib.Path) -> None:
        """AC-CYCLE-001 remediation: aligning both sources to the same SHA makes install succeed."""
        sha_a = "a" * 40
        source_a_url = "git@gitserver:org/example-package.git"
        source_b_url = "https://gitserver/org/example-package.git"

        # Both sources now declare the same revision and resolve to the same SHA
        kanon_path = _write_two_source_kanon(
            tmp_path,
            source_a_url=source_a_url,
            source_a_rev="==1.0.0",
            source_b_url=source_b_url,
            source_b_rev="==1.0.0",
        )

        sha_map = {
            source_a_url: (sha_a, "refs/tags/1.0.0"),
            source_b_url: (sha_a, "refs/tags/1.0.0"),
        }

        # Should complete without error
        _run_install_mocked(kanon_path, sha_map)

    def test_remediation_removes_one_source(self, tmp_path: pathlib.Path) -> None:
        """AC-CYCLE-001 remediation: removing one conflicting source makes install succeed."""
        sha_a = "a" * 40
        sha_b = "b" * 40
        source_a_url = "git@gitserver:org/example-package.git"
        source_b_url = "https://gitserver/org/example-package.git"

        # Both sources conflict
        conflict_dir = tmp_path / "conflict"
        conflict_dir.mkdir(parents=True, exist_ok=True)
        kanon_conflict = _write_two_source_kanon(
            conflict_dir,
            source_a_url=source_a_url,
            source_a_rev="==1.0.0",
            source_b_url=source_b_url,
            source_b_rev="==2.0.0",
        )

        sha_map_conflict = {
            source_a_url: (sha_a, "refs/tags/1.0.0"),
            source_b_url: (sha_b, "refs/tags/2.0.0"),
        }

        with pytest.raises(CanonicalUrlConflictError):
            _run_install_mocked(kanon_conflict, sha_map_conflict)

        # Remediation: single-source .kanon (conflict removed)
        fixed_dir = tmp_path / "fixed"
        fixed_dir.mkdir(parents=True, exist_ok=True)
        kanon_fixed = _write_single_source_kanon(
            fixed_dir,
            source_url=source_a_url,
            source_rev="==1.0.0",
        )
        sha_map_fixed = {source_a_url: (sha_a, "refs/tags/1.0.0")}

        # Should NOT raise -- only one source now
        _run_install_mocked(kanon_fixed, sha_map_fixed)
