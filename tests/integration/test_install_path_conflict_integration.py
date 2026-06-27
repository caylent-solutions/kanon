"""Integration tests for package-destination conflict detection in kanon install.

The install conflict check is keyed on the package DESTINATION PATH
(``.packages/<name>``), not the repository URL.  These tests drive the real
``install()`` entry point with repo-tool calls mocked, supplying each source's
captured content pins so the path-keyed detector runs end-to-end:

  - same repo, DIFFERENT paths, DIFFERENT SHAs -> success (the mono-repo case:
    install any version of package A and any version of package B from one repo).
  - same path, DIFFERENT SHAs -> ``PackagePathConflictError`` (real collision).
  - same path, same SHA -> success (benign).
  - conflict baked into the lockfile is re-detected on the consistent path.
  - remediation (align SHAs or remove a source) makes install succeed.

repo tool calls (repo_init, repo_envsubst, repo_sync) and content-pin capture
are mocked so no real checkouts or network are needed.
"""

from __future__ import annotations

import pathlib
from unittest.mock import patch

import pytest

from kanon_cli.core.include_walker import IncludeTree
from kanon_cli.core.install import (
    PackagePathConflictError,
    _RefResolution,
    install,
)
from kanon_cli.core.lockfile import ContentPinEntry


@pytest.fixture(autouse=True)
def _mock_check_sha_reachable():
    """No SHA reachability checks needed for conflict-detection tests."""
    with patch("kanon_cli.core.install._check_sha_reachable"):
        yield


@pytest.fixture(autouse=True)
def _mock_walk_includes():
    """Mock _walk_includes so tests that mock repo ops need no real XML on disk."""
    with patch(
        "kanon_cli.core.install._walk_includes",
        return_value=IncludeTree(path=pathlib.Path("manifest.xml")),
    ):
        yield


def _write_two_source_kanon(
    project_dir: pathlib.Path,
    source_a_url: str,
    source_a_rev: str,
    source_b_url: str,
    source_b_rev: str,
) -> pathlib.Path:
    """Write a two-source .kanon file (source names: alpha, bravo)."""
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
    """Write a single-source .kanon file (source name: alpha)."""
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
    pins_by_alias: dict[str, list[tuple[str, str, str]]],
) -> None:
    """Run install() with repo tool calls and content-pin capture mocked.

    ``_resolve_ref_to_sha`` resolves each URL in ``sha_map`` to its (sha, ref)
    pair.  ``capture_content_pins`` is patched to return, for the source whose
    store dir name is ``<alias>``, the ``ContentPinEntry`` rows declared in
    ``pins_by_alias[alias]`` (each a ``(name, path, sha)`` tuple) -- this is the
    per-source destination data the path-keyed detector consumes.

    Args:
        kanon_path: Path to the .kanon configuration file.
        sha_map: Maps source URL to (sha, resolved_ref) pair.
        pins_by_alias: Maps source alias to its captured (name, path, sha) pins.
    """

    def _fake_resolve_ref_to_sha(url: str, ref: str) -> _RefResolution:
        if url in sha_map:
            sha, resolved_ref = sha_map[url]
            return _RefResolution(sha=sha, resolved_ref=resolved_ref)
        raise ValueError(f"Unexpected URL in test: {url!r}")

    def _fake_resolve_version(url: str, rev_spec: str) -> str:
        if url in sha_map:
            _sha, resolved_ref = sha_map[url]
            return resolved_ref
        return rev_spec

    def _fake_capture_content_pins(
        source_dir: pathlib.Path, manifest_paths: list[pathlib.Path]
    ) -> list[ContentPinEntry]:
        rows = pins_by_alias.get(source_dir.name, [])
        return [ContentPinEntry(name=n, path=p, resolved_sha=s) for (n, p, s) in rows]

    with (
        patch("kanon_cli.core.install._resolve_ref_to_sha", side_effect=_fake_resolve_ref_to_sha),
        patch("kanon_cli.core.install.resolve_version", side_effect=_fake_resolve_version),
        patch("kanon_cli.core.install.run_repo_init"),
        patch("kanon_cli.core.install.run_repo_envsubst"),
        patch("kanon_cli.core.install.run_repo_sync"),
        patch("kanon_cli.core.install.capture_content_pins", side_effect=_fake_capture_content_pins),
    ):
        install(kanon_path, lock_file_path=kanon_path.parent / ".kanon.lock")


_SHA_A = "a" * 40
_SHA_B = "b" * 40
_MONO_REPO = "https://gitserver/org/mono-repo.git"


@pytest.mark.integration
class TestInstallPathConflict:
    def test_same_repo_different_paths_different_sha_succeeds(self, tmp_path: pathlib.Path) -> None:
        """The mono-repo case: one repo, two packages at different paths and commits, installs cleanly."""
        kanon_path = _write_two_source_kanon(
            tmp_path,
            source_a_url=_MONO_REPO,
            source_a_rev="refs/tags/control-tower/0.1.0",
            source_b_url=_MONO_REPO,
            source_b_rev="refs/tags/review-terraform/0.2.0",
        )

        def _resolve(url: str, ref: str) -> _RefResolution:
            if "review-terraform" in ref:
                return _RefResolution(sha=_SHA_B, resolved_ref="refs/tags/review-terraform/0.2.0")
            return _RefResolution(sha=_SHA_A, resolved_ref="refs/tags/control-tower/0.1.0")

        pins_by_alias = {
            "alpha": [("control-tower", ".packages/control-tower", _SHA_A)],
            "bravo": [("review-terraform", ".packages/review-terraform", _SHA_B)],
        }

        def _fake_capture(source_dir: pathlib.Path, manifest_paths: list[pathlib.Path]) -> list[ContentPinEntry]:
            rows = pins_by_alias[source_dir.name]
            return [ContentPinEntry(name=n, path=p, resolved_sha=s) for (n, p, s) in rows]

        with (
            patch("kanon_cli.core.install._resolve_ref_to_sha", side_effect=_resolve),
            patch("kanon_cli.core.install.resolve_version", side_effect=lambda url, ref: ref),
            patch("kanon_cli.core.install.run_repo_init"),
            patch("kanon_cli.core.install.run_repo_envsubst"),
            patch("kanon_cli.core.install.run_repo_sync"),
            patch("kanon_cli.core.install.capture_content_pins", side_effect=_fake_capture),
        ):
            install(kanon_path, lock_file_path=kanon_path.parent / ".kanon.lock")

    def test_same_path_different_sha_raises_conflict(self, tmp_path: pathlib.Path) -> None:
        """Two sources resolving the SAME .packages/ slot to different content -> hard error."""
        kanon_path = _write_two_source_kanon(
            tmp_path,
            source_a_url="git@gitserver:org/example-package.git",
            source_a_rev="==1.0.0",
            source_b_url="https://gitserver/org/example-package.git",
            source_b_rev="==2.0.0",
        )
        sha_map = {
            "git@gitserver:org/example-package.git": (_SHA_A, "refs/tags/1.0.0"),
            "https://gitserver/org/example-package.git": (_SHA_B, "refs/tags/2.0.0"),
        }
        pins_by_alias = {
            "alpha": [("shared", ".packages/shared", _SHA_A)],
            "bravo": [("shared", ".packages/shared", _SHA_B)],
        }

        with pytest.raises(PackagePathConflictError) as exc_info:
            _run_install_mocked(kanon_path, sha_map, pins_by_alias)

        msg = str(exc_info.value)
        assert ".packages/shared" in msg
        assert "alpha" in msg
        assert "bravo" in msg
        assert _SHA_A in msg
        assert _SHA_B in msg

    def test_same_path_same_sha_no_conflict(self, tmp_path: pathlib.Path) -> None:
        """Two sources placing the same package at the same commit -> benign, installs."""
        kanon_path = _write_two_source_kanon(
            tmp_path,
            source_a_url="git@gitserver:org/example-package.git",
            source_a_rev="==1.0.0",
            source_b_url="https://gitserver/org/example-package.git",
            source_b_rev="==1.0.0",
        )
        sha_map = {
            "git@gitserver:org/example-package.git": (_SHA_A, "refs/tags/1.0.0"),
            "https://gitserver/org/example-package.git": (_SHA_A, "refs/tags/1.0.0"),
        }
        pins_by_alias = {
            "alpha": [("shared", ".packages/shared", _SHA_A)],
            "bravo": [("shared", ".packages/shared", _SHA_A)],
        }

        _run_install_mocked(kanon_path, sha_map, pins_by_alias)

    def test_conflict_detected_on_lockfile_consistent_path(self, tmp_path: pathlib.Path) -> None:
        """A same-path/different-SHA conflict baked into the lockfile is re-detected on replay."""
        import datetime

        from kanon_cli.core.kanon_hash import kanon_hash
        from kanon_cli.core.lockfile import (
            CURRENT_SCHEMA_VERSION,
            Lockfile,
            SourceEntry,
            write_lockfile,
        )

        source_a_url = "git@gitserver:org/example-package.git"
        source_b_url = "https://gitserver/org/example-package.git"
        kanon_path = _write_two_source_kanon(
            tmp_path,
            source_a_url=source_a_url,
            source_a_rev="==1.0.0",
            source_b_url=source_b_url,
            source_b_rev="==2.0.0",
        )
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
                    resolved_sha=_SHA_A,
                    path="manifest.xml",
                    content_pins=[ContentPinEntry(name="shared", path=".packages/shared", resolved_sha=_SHA_A)],
                ),
                SourceEntry(
                    alias="bravo",
                    name="bravo",
                    url=source_b_url,
                    ref_spec="==2.0.0",
                    resolved_ref="refs/tags/2.0.0",
                    resolved_sha=_SHA_B,
                    path="manifest.xml",
                    content_pins=[ContentPinEntry(name="shared", path=".packages/shared", resolved_sha=_SHA_B)],
                ),
            ],
        )
        write_lockfile(lf, lockfile_path)

        with (
            patch("kanon_cli.core.install.run_repo_init"),
            patch("kanon_cli.core.install.run_repo_envsubst"),
            patch("kanon_cli.core.install.run_repo_sync"),
        ):
            with pytest.raises(PackagePathConflictError) as exc_info:
                install(kanon_path, lock_file_path=lockfile_path)

        msg = str(exc_info.value)
        assert ".packages/shared" in msg
        assert _SHA_A in msg
        assert _SHA_B in msg

    def test_align_shas_resolves_conflict(self, tmp_path: pathlib.Path) -> None:
        """Remediation: aligning the shared path to one SHA makes install succeed."""
        kanon_path = _write_two_source_kanon(
            tmp_path,
            source_a_url="git@gitserver:org/example-package.git",
            source_a_rev="==1.0.0",
            source_b_url="https://gitserver/org/example-package.git",
            source_b_rev="==1.0.0",
        )
        sha_map = {
            "git@gitserver:org/example-package.git": (_SHA_A, "refs/tags/1.0.0"),
            "https://gitserver/org/example-package.git": (_SHA_A, "refs/tags/1.0.0"),
        }
        pins_by_alias = {
            "alpha": [("shared", ".packages/shared", _SHA_A)],
            "bravo": [("shared", ".packages/shared", _SHA_A)],
        }
        _run_install_mocked(kanon_path, sha_map, pins_by_alias)

    def test_remediation_removes_one_source(self, tmp_path: pathlib.Path) -> None:
        """Remediation: removing one conflicting source makes install succeed."""
        conflict_dir = tmp_path / "conflict"
        conflict_dir.mkdir(parents=True, exist_ok=True)
        kanon_conflict = _write_two_source_kanon(
            conflict_dir,
            source_a_url="git@gitserver:org/example-package.git",
            source_a_rev="==1.0.0",
            source_b_url="https://gitserver/org/example-package.git",
            source_b_rev="==2.0.0",
        )
        sha_map_conflict = {
            "git@gitserver:org/example-package.git": (_SHA_A, "refs/tags/1.0.0"),
            "https://gitserver/org/example-package.git": (_SHA_B, "refs/tags/2.0.0"),
        }
        pins_conflict = {
            "alpha": [("shared", ".packages/shared", _SHA_A)],
            "bravo": [("shared", ".packages/shared", _SHA_B)],
        }
        with pytest.raises(PackagePathConflictError):
            _run_install_mocked(kanon_conflict, sha_map_conflict, pins_conflict)

        fixed_dir = tmp_path / "fixed"
        fixed_dir.mkdir(parents=True, exist_ok=True)
        kanon_fixed = _write_single_source_kanon(
            fixed_dir,
            source_url="git@gitserver:org/example-package.git",
            source_rev="==1.0.0",
        )
        sha_map_fixed = {"git@gitserver:org/example-package.git": (_SHA_A, "refs/tags/1.0.0")}
        pins_fixed = {"alpha": [("shared", ".packages/shared", _SHA_A)]}
        _run_install_mocked(kanon_fixed, sha_map_fixed, pins_fixed)
