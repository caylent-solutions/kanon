"""Regression tests for the tempfile inode-leak fix in test_project_coverage_threshold.

Covers:
- AC-TEST-001: helpers create real dirs; _cleanup_tracked_tempdirs removes them.
- AC-TEST-002: _cleanup_tracked_tempdirs is registered with atexit at import time.
- AC-TEST-003: _cleanup_tracked_tempdirs is idempotent (second call is a no-op).
"""

import atexit
import os
from unittest import mock

import pytest

import tests.unit.repo.test_project_coverage_threshold as module_under_test


@pytest.mark.unit
class TestMkdtempCleanupHelpers:
    """AC-TEST-001: helpers produce real directories that are cleaned up."""

    def test_make_project_creates_real_directories(self):
        """_make_project() returns a project whose manifest.topdir exists on disk."""
        # Reset tracked list so previous test runs do not pollute counts.
        original_tracked = list(module_under_test._TRACKED_TEMPDIRS)
        module_under_test._TRACKED_TEMPDIRS.clear()

        projs = [module_under_test._make_project() for _ in range(3)]
        dirs = [p.manifest.topdir for p in projs]

        # Every directory must exist right after the helper returns.
        for d in dirs:
            assert os.path.isdir(d), f"expected {d!r} to exist after _make_project()"

        # Invoke the cleanup callback directly.
        module_under_test._cleanup_tracked_tempdirs()

        # Every directory must now be gone.
        for d in dirs:
            assert not os.path.exists(d), f"expected {d!r} to be removed after cleanup"

        # Restore original tracked list.
        module_under_test._TRACKED_TEMPDIRS.extend(original_tracked)

    def test_make_meta_project_creates_real_directory_when_manifest_lacks_repodir(self):
        """_make_meta_project() falls back to mkdtemp when manifest.repodir is falsy."""
        original_tracked = list(module_under_test._TRACKED_TEMPDIRS)
        module_under_test._TRACKED_TEMPDIRS.clear()

        manifest = mock.MagicMock()
        # Force the fallback branch by returning a falsy value from .repodir.
        manifest.repodir = None

        for _ in range(3):
            module_under_test._make_meta_project(manifest)

        # When manifest.repodir is falsy, each call should produce a distinct tmpdir.
        # The worktree path has a suffix; gitdir is just the repodir itself.
        # We confirm at least 3 paths were tracked (one per call).
        assert len(module_under_test._TRACKED_TEMPDIRS) >= 3, (
            "expected at least 3 entries in _TRACKED_TEMPDIRS after 3 _make_meta_project calls"
        )

        dirs = list(module_under_test._TRACKED_TEMPDIRS)
        for d in dirs:
            assert os.path.isdir(d), f"expected {d!r} to exist after _make_meta_project()"

        module_under_test._cleanup_tracked_tempdirs()

        for d in dirs:
            assert not os.path.exists(d), f"expected {d!r} to be removed after _cleanup_tracked_tempdirs()"

        module_under_test._TRACKED_TEMPDIRS.extend(original_tracked)

    def test_make_meta_project_does_not_track_when_manifest_has_repodir(self):
        """_make_meta_project() does NOT create a new tmpdir when manifest.repodir is set."""
        original_tracked = list(module_under_test._TRACKED_TEMPDIRS)
        module_under_test._TRACKED_TEMPDIRS.clear()

        manifest = mock.MagicMock()
        manifest.repodir = "/tmp/some-existing-path"  # truthy -- no mkdtemp call expected

        module_under_test._make_meta_project(manifest)

        # No new directories should have been appended to _TRACKED_TEMPDIRS.
        assert len(module_under_test._TRACKED_TEMPDIRS) == 0, (
            "expected zero entries in _TRACKED_TEMPDIRS when manifest.repodir is set"
        )

        module_under_test._TRACKED_TEMPDIRS.extend(original_tracked)


@pytest.mark.unit
class TestAtexitRegistration:
    """AC-TEST-002: _cleanup_tracked_tempdirs is registered with atexit."""

    def test_cleanup_function_is_registered_with_atexit(self):
        """Verify _cleanup_tracked_tempdirs is a registered atexit callback.

        Strategy: record the callback count, unregister the function, confirm the
        count decreases, then re-register to leave the interpreter state intact.
        """
        before = atexit._ncallbacks()
        atexit.unregister(module_under_test._cleanup_tracked_tempdirs)
        after = atexit._ncallbacks()

        try:
            assert before - after >= 1, (
                "_cleanup_tracked_tempdirs was not registered with atexit "
                f"(ncallbacks before={before}, after unregister={after})"
            )
        finally:
            # Re-register so interpreter exit still cleans up.
            atexit.register(module_under_test._cleanup_tracked_tempdirs)


@pytest.mark.unit
class TestCleanupIdempotence:
    """AC-TEST-003: _cleanup_tracked_tempdirs is idempotent."""

    def test_second_call_is_a_noop_and_does_not_raise(self, tmp_path):
        """Calling _cleanup_tracked_tempdirs twice must not raise."""
        original_tracked = list(module_under_test._TRACKED_TEMPDIRS)
        module_under_test._TRACKED_TEMPDIRS.clear()

        # Add one real directory and one already-removed path.
        real_dir = str(tmp_path / "cleanup-test")
        os.makedirs(real_dir)
        module_under_test._TRACKED_TEMPDIRS.append(real_dir)

        module_under_test._cleanup_tracked_tempdirs()
        assert not os.path.exists(real_dir), "first call should remove the directory"

        # Second call -- directory is already gone; must not raise.
        module_under_test._cleanup_tracked_tempdirs()

        module_under_test._TRACKED_TEMPDIRS.extend(original_tracked)
