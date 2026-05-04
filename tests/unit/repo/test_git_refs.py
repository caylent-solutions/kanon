# Copyright (C) 2009 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unittests for the git_refs.py module."""

import os
import tempfile
import unittest

import pytest

from kanon_cli.repo import git_refs


@pytest.mark.unit
class TestGitRefsConstants(unittest.TestCase):
    """Tests for git_refs constants."""

    def test_HEAD_constant(self):
        """Test HEAD constant value."""
        self.assertEqual(git_refs.HEAD, "HEAD")

    def test_R_CHANGES_constant(self):
        """Test R_CHANGES constant value."""
        self.assertEqual(git_refs.R_CHANGES, "refs/changes/")

    def test_R_HEADS_constant(self):
        """Test R_HEADS constant value."""
        self.assertEqual(git_refs.R_HEADS, "refs/heads/")

    def test_R_TAGS_constant(self):
        """Test R_TAGS constant value."""
        self.assertEqual(git_refs.R_TAGS, "refs/tags/")

    def test_R_PUB_constant(self):
        """Test R_PUB constant value."""
        self.assertEqual(git_refs.R_PUB, "refs/published/")

    def test_R_WORKTREE_constant(self):
        """Test R_WORKTREE constant value."""
        self.assertEqual(git_refs.R_WORKTREE, "refs/worktree/")

    def test_R_WORKTREE_M_constant(self):
        """Test R_WORKTREE_M constant value."""
        self.assertEqual(git_refs.R_WORKTREE_M, "refs/worktree/m/")

    def test_R_M_constant(self):
        """Test R_M constant value."""
        self.assertEqual(git_refs.R_M, "refs/remotes/m/")


@pytest.mark.unit
class TestGitRefs(unittest.TestCase):
    """Tests for GitRefs class."""

    def setUp(self):
        """Set up test fixtures."""
        self.tempdir = tempfile.mkdtemp()
        self.gitdir = os.path.join(self.tempdir, ".git")
        os.makedirs(self.gitdir)

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil

        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_init(self):
        """Test GitRefs initialization."""
        refs = git_refs.GitRefs(self.gitdir)
        self.assertEqual(refs._gitdir, self.gitdir)
        self.assertIsNone(refs._phyref)
        self.assertIsNone(refs._symref)

    def test_get_missing_ref(self):
        """Test get() with missing ref returns empty string."""
        # Create refs directory to avoid FileNotFoundError
        os.makedirs(os.path.join(self.gitdir, "refs"))
        refs = git_refs.GitRefs(self.gitdir)
        self.assertEqual(refs.get("refs/heads/main"), "")

    def test_get_existing_ref(self):
        """Test get() with existing ref."""
        # Create a ref file
        refs_dir = os.path.join(self.gitdir, "refs", "heads")
        os.makedirs(refs_dir)
        ref_file = os.path.join(refs_dir, "main")
        commit_id = "a" * 40
        with open(ref_file, "w") as f:
            f.write(commit_id + "\n")

        refs = git_refs.GitRefs(self.gitdir)
        self.assertEqual(refs.get("refs/heads/main"), commit_id)

    def test_symref(self):
        """Test symref() returns symbolic reference."""
        # Create refs directory to avoid FileNotFoundError
        os.makedirs(os.path.join(self.gitdir, "refs"))
        # Create HEAD as symbolic ref
        head_file = os.path.join(self.gitdir, "HEAD")
        with open(head_file, "w") as f:
            f.write("ref: refs/heads/main\n")

        refs = git_refs.GitRefs(self.gitdir)
        self.assertEqual(refs.symref("HEAD"), "refs/heads/main")

    def test_symref_missing(self):
        """Test symref() with missing ref returns empty string."""
        # Create refs directory to avoid FileNotFoundError
        os.makedirs(os.path.join(self.gitdir, "refs"))
        refs = git_refs.GitRefs(self.gitdir)
        self.assertEqual(refs.symref("missing"), "")

    def test_deleted(self):
        """Test deleted() removes ref from cache."""
        # Create a ref
        refs_dir = os.path.join(self.gitdir, "refs", "heads")
        os.makedirs(refs_dir)
        ref_file = os.path.join(refs_dir, "branch")
        with open(ref_file, "w") as f:
            f.write("a" * 40 + "\n")

        refs = git_refs.GitRefs(self.gitdir)
        # Load refs
        _ = refs.get("refs/heads/branch")

        # Delete the ref
        refs.deleted("refs/heads/branch")

        # Verify it's removed from cache
        self.assertNotIn("refs/heads/branch", refs._phyref)

    def test_deleted_when_not_loaded(self):
        """Test deleted() when refs not yet loaded."""
        refs = git_refs.GitRefs(self.gitdir)
        # Should not raise exception
        refs.deleted("refs/heads/nonexistent")

    def test_all_property(self):
        """Test all property returns all physical refs."""
        # Create multiple refs
        refs_dir = os.path.join(self.gitdir, "refs", "heads")
        os.makedirs(refs_dir)
        for branch in ["main", "dev", "feature"]:
            with open(os.path.join(refs_dir, branch), "w") as f:
                f.write("a" * 40 + "\n")

        refs = git_refs.GitRefs(self.gitdir)
        all_refs = refs.all
        self.assertIn("refs/heads/main", all_refs)
        self.assertIn("refs/heads/dev", all_refs)
        self.assertIn("refs/heads/feature", all_refs)

    def test_ReadPackedRefs(self):
        """Test _ReadPackedRefs() reads packed-refs file."""
        # Create packed-refs file
        packed_refs = os.path.join(self.gitdir, "packed-refs")
        commit_id = "b" * 40
        with open(packed_refs, "w") as f:
            f.write("# pack-refs with: peeled fully-peeled sorted\n")
            f.write(f"{commit_id} refs/heads/main\n")
            f.write(f"{'c' * 40} refs/heads/dev\n")

        refs = git_refs.GitRefs(self.gitdir)
        refs._phyref = {}  # Initialize before calling _ReadPackedRefs
        refs._symref = {}
        refs._ReadPackedRefs()

        self.assertEqual(refs._phyref["refs/heads/main"], commit_id)
        self.assertEqual(refs._phyref["refs/heads/dev"], "c" * 40)

    def test_ReadPackedRefs_ignores_comments(self):
        """Test _ReadPackedRefs() ignores comment lines."""
        packed_refs = os.path.join(self.gitdir, "packed-refs")
        with open(packed_refs, "w") as f:
            f.write("# This is a comment\n")
            f.write(f"{'a' * 40} refs/heads/main\n")

        refs = git_refs.GitRefs(self.gitdir)
        refs._phyref = {}  # Initialize before calling _ReadPackedRefs
        refs._symref = {}
        refs._ReadPackedRefs()

        self.assertIn("refs/heads/main", refs._phyref)

    def test_ReadPackedRefs_ignores_peeled(self):
        """Test _ReadPackedRefs() ignores peeled refs (^)."""
        packed_refs = os.path.join(self.gitdir, "packed-refs")
        with open(packed_refs, "w") as f:
            f.write(f"{'a' * 40} refs/tags/v1.0\n")
            f.write(f"^{'b' * 40}\n")

        refs = git_refs.GitRefs(self.gitdir)
        refs._phyref = {}  # Initialize before calling _ReadPackedRefs
        refs._symref = {}
        refs._ReadPackedRefs()

        self.assertIn("refs/tags/v1.0", refs._phyref)
        # Peeled ref should not be added

    def test_ReadPackedRefs_missing_file(self):
        """Test _ReadPackedRefs() handles missing file."""
        refs = git_refs.GitRefs(self.gitdir)
        refs._phyref = {}  # Initialize before calling _ReadPackedRefs
        refs._symref = {}
        # Should not raise exception
        refs._ReadPackedRefs()
        self.assertEqual(len(refs._phyref), 0)

    def test_ReadLoose_reads_refs(self):
        """Test _ReadLoose() reads loose refs."""
        # Create refs directory structure
        refs_dir = os.path.join(self.gitdir, "refs", "heads")
        os.makedirs(refs_dir)
        with open(os.path.join(refs_dir, "main"), "w") as f:
            f.write("a" * 40 + "\n")
        with open(os.path.join(refs_dir, "dev"), "w") as f:
            f.write("b" * 40 + "\n")

        refs = git_refs.GitRefs(self.gitdir)
        refs._phyref = {}  # Initialize before calling _ReadLoose
        refs._symref = {}
        refs._mtime = {}
        refs._ReadLoose("refs/")

        self.assertIn("refs/heads/main", refs._phyref)
        self.assertIn("refs/heads/dev", refs._phyref)

    def test_ReadLoose_skips_dotfiles(self):
        """Test _ReadLoose() skips files starting with dot."""
        refs_dir = os.path.join(self.gitdir, "refs", "heads")
        os.makedirs(refs_dir)
        with open(os.path.join(refs_dir, ".hidden"), "w") as f:
            f.write("a" * 40 + "\n")

        refs = git_refs.GitRefs(self.gitdir)
        refs._phyref = {}  # Initialize before calling _ReadLoose
        refs._symref = {}
        refs._mtime = {}
        refs._ReadLoose("refs/")

        self.assertNotIn("refs/heads/.hidden", refs._phyref)

    def test_ReadLoose_skips_lock_files(self):
        """Test _ReadLoose() skips .lock files."""
        refs_dir = os.path.join(self.gitdir, "refs", "heads")
        os.makedirs(refs_dir)
        with open(os.path.join(refs_dir, "main.lock"), "w") as f:
            f.write("a" * 40 + "\n")

        refs = git_refs.GitRefs(self.gitdir)
        refs._phyref = {}  # Initialize before calling _ReadLoose
        refs._symref = {}
        refs._mtime = {}
        refs._ReadLoose("refs/")

        self.assertNotIn("refs/heads/main.lock", refs._phyref)

    def test_ReadLoose_recurses_directories(self):
        """Test _ReadLoose() recurses into subdirectories."""
        refs_dir = os.path.join(self.gitdir, "refs", "heads", "feature")
        os.makedirs(refs_dir)
        with open(os.path.join(refs_dir, "branch1"), "w") as f:
            f.write("a" * 40 + "\n")

        refs = git_refs.GitRefs(self.gitdir)
        refs._phyref = {}  # Initialize before calling _ReadLoose
        refs._symref = {}
        refs._mtime = {}
        refs._ReadLoose("refs/")

        self.assertIn("refs/heads/feature/branch1", refs._phyref)

    def test_ReadLoose1_reads_ref(self):
        """Test _ReadLoose1() reads a single ref."""
        ref_file = os.path.join(self.gitdir, "refs", "heads", "main")
        os.makedirs(os.path.dirname(ref_file))
        commit_id = "a" * 40
        with open(ref_file, "w") as f:
            f.write(commit_id + "\n")

        refs = git_refs.GitRefs(self.gitdir)
        refs._phyref = {}  # Initialize before calling _ReadLoose1
        refs._symref = {}
        refs._mtime = {}
        refs._ReadLoose1(ref_file, "refs/heads/main")

        self.assertEqual(refs._phyref["refs/heads/main"], commit_id)

    def test_ReadLoose1_reads_symref(self):
        """Test _ReadLoose1() reads symbolic reference."""
        head_file = os.path.join(self.gitdir, "HEAD")
        with open(head_file, "w") as f:
            f.write("ref: refs/heads/main\n")

        refs = git_refs.GitRefs(self.gitdir)
        refs._phyref = {}  # Initialize before calling _ReadLoose1
        refs._symref = {}
        refs._mtime = {}
        refs._ReadLoose1(head_file, "HEAD")

        self.assertEqual(refs._symref["HEAD"], "refs/heads/main")

    def test_ReadLoose1_handles_missing_file(self):
        """Test _ReadLoose1() handles missing file."""
        refs = git_refs.GitRefs(self.gitdir)
        # Should not raise exception
        refs._ReadLoose1("/nonexistent/file", "refs/heads/missing")

    def test_LoadAll_loads_all_refs(self):
        """Test _LoadAll() loads all refs."""
        # Create HEAD
        with open(os.path.join(self.gitdir, "HEAD"), "w") as f:
            f.write("ref: refs/heads/main\n")

        # Create loose ref
        refs_dir = os.path.join(self.gitdir, "refs", "heads")
        os.makedirs(refs_dir)
        with open(os.path.join(refs_dir, "main"), "w") as f:
            f.write("a" * 40 + "\n")

        # Create packed refs
        with open(os.path.join(self.gitdir, "packed-refs"), "w") as f:
            f.write(f"{'b' * 40} refs/heads/dev\n")

        refs = git_refs.GitRefs(self.gitdir)
        refs._LoadAll()

        self.assertIn("HEAD", refs._symref)
        self.assertIn("refs/heads/main", refs._phyref)
        self.assertIn("refs/heads/dev", refs._phyref)

    def test_LoadAll_resolves_symrefs(self):
        """Test _LoadAll() resolves symbolic references."""
        # Create HEAD pointing to main
        with open(os.path.join(self.gitdir, "HEAD"), "w") as f:
            f.write("ref: refs/heads/main\n")

        # Create main ref
        refs_dir = os.path.join(self.gitdir, "refs", "heads")
        os.makedirs(refs_dir)
        commit_id = "a" * 40
        with open(os.path.join(refs_dir, "main"), "w") as f:
            f.write(commit_id + "\n")

        refs = git_refs.GitRefs(self.gitdir)
        refs._LoadAll()

        # HEAD should resolve to the commit ID
        self.assertEqual(refs._phyref["HEAD"], commit_id)

    def test_NeedUpdate_returns_false_when_no_changes(self):
        """Test _NeedUpdate() returns False when no changes."""
        # Create a ref
        refs_dir = os.path.join(self.gitdir, "refs", "heads")
        os.makedirs(refs_dir)
        ref_file = os.path.join(refs_dir, "main")
        with open(ref_file, "w") as f:
            f.write("a" * 40 + "\n")

        refs = git_refs.GitRefs(self.gitdir)
        refs._LoadAll()

        # No changes
        self.assertFalse(refs._NeedUpdate())

    def test_NeedUpdate_returns_true_when_file_modified(self):
        """Test _NeedUpdate() returns True when file modified."""
        # Create a ref
        refs_dir = os.path.join(self.gitdir, "refs", "heads")
        os.makedirs(refs_dir)
        ref_file = os.path.join(refs_dir, "main")
        with open(ref_file, "w") as f:
            f.write("a" * 40 + "\n")

        refs = git_refs.GitRefs(self.gitdir)
        refs._LoadAll()

        # Modify the file
        import time

        time.sleep(0.01)  # Ensure mtime changes
        with open(ref_file, "w") as f:
            f.write("b" * 40 + "\n")

        self.assertTrue(refs._NeedUpdate())

    def test_NeedUpdate_returns_true_when_file_deleted(self):
        """Test _NeedUpdate() returns True when file deleted."""
        # Create a ref
        refs_dir = os.path.join(self.gitdir, "refs", "heads")
        os.makedirs(refs_dir)
        ref_file = os.path.join(refs_dir, "main")
        with open(ref_file, "w") as f:
            f.write("a" * 40 + "\n")

        refs = git_refs.GitRefs(self.gitdir)
        refs._LoadAll()

        # Delete the file
        os.remove(ref_file)

        self.assertTrue(refs._NeedUpdate())

    def test_EnsureLoaded_loads_when_not_loaded(self):
        """Test _EnsureLoaded() loads refs when not loaded."""
        # Create refs directory to avoid FileNotFoundError
        os.makedirs(os.path.join(self.gitdir, "refs"))
        refs = git_refs.GitRefs(self.gitdir)
        self.assertIsNone(refs._phyref)

        refs._EnsureLoaded()

        self.assertIsNotNone(refs._phyref)
        self.assertIsNotNone(refs._symref)

    def test_EnsureLoaded_reloads_when_needed(self):
        """Test _EnsureLoaded() reloads when updates detected."""
        # Create a ref
        refs_dir = os.path.join(self.gitdir, "refs", "heads")
        os.makedirs(refs_dir)
        ref_file = os.path.join(refs_dir, "main")
        with open(ref_file, "w") as f:
            f.write("a" * 40 + "\n")

        refs = git_refs.GitRefs(self.gitdir)
        refs._EnsureLoaded()
        old_commit = refs.get("refs/heads/main")

        # Modify the file
        import time

        time.sleep(0.01)
        with open(ref_file, "w") as f:
            f.write("b" * 40 + "\n")

        refs._EnsureLoaded()
        new_commit = refs.get("refs/heads/main")

        self.assertNotEqual(old_commit, new_commit)
        self.assertEqual(new_commit, "b" * 40)


@pytest.mark.unit
class TestGitRefsEdgeCases(unittest.TestCase):
    """Tests for GitRefs edge cases."""

    def setUp(self):
        """Set up test fixtures."""
        self.tempdir = tempfile.mkdtemp()
        self.gitdir = os.path.join(self.tempdir, ".git")
        os.makedirs(self.gitdir)

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil

        shutil.rmtree(self.tempdir, ignore_errors=True)

    def test_ReadLoose1_with_bytes_content(self):
        """Test _ReadLoose1() handles bytes content."""
        ref_file = os.path.join(self.gitdir, "refs", "heads", "main")
        os.makedirs(os.path.dirname(ref_file))
        with open(ref_file, "wb") as f:
            f.write(b"a" * 40 + b"\n")

        refs = git_refs.GitRefs(self.gitdir)
        refs._phyref = {}  # Initialize before calling _ReadLoose1
        refs._symref = {}
        refs._mtime = {}
        refs._ReadLoose1(ref_file, "refs/heads/main")

        self.assertEqual(refs._phyref["refs/heads/main"], "a" * 40)

    def test_ReadLoose1_with_empty_file(self):
        """Test _ReadLoose1() handles empty file."""
        ref_file = os.path.join(self.gitdir, "refs", "heads", "empty")
        os.makedirs(os.path.dirname(ref_file))
        with open(ref_file, "w") as f:
            f.write("")

        refs = git_refs.GitRefs(self.gitdir)
        refs._phyref = {}  # Initialize before calling _ReadLoose1
        refs._symref = {}
        refs._mtime = {}
        refs._ReadLoose1(ref_file, "refs/heads/empty")

        # Empty file should not add ref
        self.assertNotIn("refs/heads/empty", refs._phyref)

    def test_symref_chain_resolution(self):
        """Test resolution of chained symbolic references."""
        # Create chain: HEAD -> refs/heads/main -> refs/heads/master
        with open(os.path.join(self.gitdir, "HEAD"), "w") as f:
            f.write("ref: refs/heads/main\n")

        refs_dir = os.path.join(self.gitdir, "refs", "heads")
        os.makedirs(refs_dir)
        with open(os.path.join(refs_dir, "main"), "w") as f:
            f.write("ref: refs/heads/master\n")

        commit_id = "a" * 40
        with open(os.path.join(refs_dir, "master"), "w") as f:
            f.write(commit_id + "\n")

        refs = git_refs.GitRefs(self.gitdir)
        refs._LoadAll()

        # HEAD should resolve to the commit ID
        self.assertEqual(refs.get("HEAD"), commit_id)

    def test_deleted_removes_from_all_caches(self):
        """Test deleted() removes from all caches."""
        # Create a symbolic ref
        with open(os.path.join(self.gitdir, "HEAD"), "w") as f:
            f.write("ref: refs/heads/main\n")

        refs_dir = os.path.join(self.gitdir, "refs", "heads")
        os.makedirs(refs_dir)
        with open(os.path.join(refs_dir, "main"), "w") as f:
            f.write("a" * 40 + "\n")

        refs = git_refs.GitRefs(self.gitdir)
        refs._LoadAll()

        # Delete HEAD
        refs.deleted("HEAD")

        self.assertNotIn("HEAD", refs._phyref)
        self.assertNotIn("HEAD", refs._symref)
        self.assertNotIn("HEAD", refs._mtime)
