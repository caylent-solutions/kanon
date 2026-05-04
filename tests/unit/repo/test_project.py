# Copyright (C) 2019 The Android Open Source Project
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

"""Unittests for the project.py module."""

import contextlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import pytest

from kanon_cli.repo import error
from kanon_cli.repo import git_command
from kanon_cli.repo import git_config
from kanon_cli.repo import manifest_xml
from kanon_cli.repo import platform_utils
from kanon_cli.repo import project


@contextlib.contextmanager
def TempGitTree():
    """Create a new empty git checkout for testing."""
    with tempfile.TemporaryDirectory(prefix="repo-tests") as tempdir:
        # Tests need to assume, that main is default branch at init,
        # which is not supported in config until 2.28.
        cmd = ["git", "init"]
        if git_command.git_require((2, 28, 0)):
            cmd += ["--initial-branch=main"]
        else:
            # Use template dir for init.
            templatedir = tempfile.mkdtemp(prefix=".test-template")
            with open(os.path.join(templatedir, "HEAD"), "w") as fp:
                fp.write("ref: refs/heads/main\n")
            cmd += ["--template", templatedir]
        subprocess.check_call(cmd, cwd=tempdir)
        yield tempdir


class FakeProject:
    """A fake for Project for basic functionality."""

    def __init__(self, worktree):
        self.worktree = worktree
        self.gitdir = os.path.join(worktree, ".git")
        self.name = "fakeproject"
        self.work_git = project.Project._GitGetByExec(self, bare=False, gitdir=self.gitdir)
        self.bare_git = project.Project._GitGetByExec(self, bare=True, gitdir=self.gitdir)
        self.config = git_config.GitConfig.ForRepository(gitdir=self.gitdir)


class ReviewableBranchTests(unittest.TestCase):
    """Check ReviewableBranch behavior."""

    def test_smoke(self):
        """A quick run through everything."""
        with TempGitTree() as tempdir:
            fakeproj = FakeProject(tempdir)

            # Generate some commits.
            with open(os.path.join(tempdir, "readme"), "w") as fp:
                fp.write("txt")
            fakeproj.work_git.add("readme")
            fakeproj.work_git.commit("-mAdd file")
            fakeproj.work_git.checkout("-b", "work")
            fakeproj.work_git.rm("-f", "readme")
            fakeproj.work_git.commit("-mDel file")

            # Start off with the normal details.
            rb = project.ReviewableBranch(fakeproj, fakeproj.config.GetBranch("work"), "main")
            self.assertEqual("work", rb.name)
            self.assertEqual(1, len(rb.commits))
            self.assertIn("Del file", rb.commits[0])
            d = rb.unabbrev_commits
            self.assertEqual(1, len(d))
            short, long = next(iter(d.items()))
            self.assertTrue(long.startswith(short))
            self.assertTrue(rb.base_exists)
            # Hard to assert anything useful about this.
            self.assertTrue(rb.date)

            # Now delete the tracking branch!
            fakeproj.work_git.branch("-D", "main")
            rb = project.ReviewableBranch(fakeproj, fakeproj.config.GetBranch("work"), "main")
            self.assertEqual(0, len(rb.commits))
            self.assertFalse(rb.base_exists)
            # Hard to assert anything useful about this.
            self.assertTrue(rb.date)


class ProjectTests(unittest.TestCase):
    """Check Project behavior."""

    def test_encode_patchset_description(self):
        self.assertEqual(
            project.Project._encode_patchset_description("abcd00!! +"),
            "abcd00%21%21_%2b",
        )


class CopyLinkTestCase(unittest.TestCase):
    """TestCase for stub repo client checkouts.

    It'll have a layout like this:
      tempdir/          # self.tempdir
        checkout/       # self.topdir
          git-project/  # self.worktree

    Attributes:
      tempdir: A dedicated temporary directory.
      worktree: The top of the repo client checkout.
      topdir: The top of a project checkout.
    """

    def setUp(self):
        self.tempdirobj = tempfile.TemporaryDirectory(prefix="repo_tests")
        self.tempdir = self.tempdirobj.name
        self.topdir = os.path.join(self.tempdir, "checkout")
        self.worktree = os.path.join(self.topdir, "git-project")
        os.makedirs(self.topdir)
        os.makedirs(self.worktree)

    def tearDown(self):
        self.tempdirobj.cleanup()

    @staticmethod
    def touch(path):
        with open(path, "w"):
            pass

    def assertExists(self, path, msg=None):
        """Make sure |path| exists."""
        if os.path.exists(path):
            return

        if msg is None:
            msg = ["path is missing: %s" % path]
            while path != "/":
                path = os.path.dirname(path)
                if not path:
                    # If we're given something like "foo", abort once we get to
                    # "".
                    break
                result = os.path.exists(path)
                msg.append(f"\tos.path.exists({path}): {result}")
                if result:
                    msg.append("\tcontents: %r" % os.listdir(path))
                    break
            msg = "\n".join(msg)

        raise self.failureException(msg)


class CopyFile(CopyLinkTestCase):
    """Check _CopyFile handling."""

    def CopyFile(self, src, dest):
        return project._CopyFile(self.worktree, src, self.topdir, dest)

    def test_basic(self):
        """Basic test of copying a file from a project to the toplevel."""
        src = os.path.join(self.worktree, "foo.txt")
        self.touch(src)
        cf = self.CopyFile("foo.txt", "foo")
        cf._Copy()
        self.assertExists(os.path.join(self.topdir, "foo"))

    def test_src_subdir(self):
        """Copy a file from a subdir of a project."""
        src = os.path.join(self.worktree, "bar", "foo.txt")
        os.makedirs(os.path.dirname(src))
        self.touch(src)
        cf = self.CopyFile("bar/foo.txt", "new.txt")
        cf._Copy()
        self.assertExists(os.path.join(self.topdir, "new.txt"))

    def test_dest_subdir(self):
        """Copy a file to a subdir of a checkout."""
        src = os.path.join(self.worktree, "foo.txt")
        self.touch(src)
        cf = self.CopyFile("foo.txt", "sub/dir/new.txt")
        self.assertFalse(os.path.exists(os.path.join(self.topdir, "sub")))
        cf._Copy()
        self.assertExists(os.path.join(self.topdir, "sub", "dir", "new.txt"))

    def test_update(self):
        """Make sure changed files get copied again."""
        src = os.path.join(self.worktree, "foo.txt")
        dest = os.path.join(self.topdir, "bar")
        with open(src, "w") as f:
            f.write("1st")
        cf = self.CopyFile("foo.txt", "bar")
        cf._Copy()
        self.assertExists(dest)
        with open(dest) as f:
            self.assertEqual(f.read(), "1st")

        with open(src, "w") as f:
            f.write("2nd!")
        cf._Copy()
        with open(dest) as f:
            self.assertEqual(f.read(), "2nd!")

    def test_src_block_symlink(self):
        """Do not allow reading from a symlinked path."""
        src = os.path.join(self.worktree, "foo.txt")
        sym = os.path.join(self.worktree, "sym")
        self.touch(src)
        platform_utils.symlink("foo.txt", sym)
        self.assertExists(sym)
        cf = self.CopyFile("sym", "foo")
        self.assertRaises(error.ManifestInvalidPathError, cf._Copy)

    def test_src_block_symlink_traversal(self):
        """Do not allow reading through a symlink dir."""
        realfile = os.path.join(self.tempdir, "file.txt")
        self.touch(realfile)
        src = os.path.join(self.worktree, "bar", "file.txt")
        platform_utils.symlink(self.tempdir, os.path.join(self.worktree, "bar"))
        self.assertExists(src)
        cf = self.CopyFile("bar/file.txt", "foo")
        self.assertRaises(error.ManifestInvalidPathError, cf._Copy)

    def test_src_block_copy_from_dir(self):
        """Do not allow copying from a directory."""
        src = os.path.join(self.worktree, "dir")
        os.makedirs(src)
        cf = self.CopyFile("dir", "foo")
        self.assertRaises(error.ManifestInvalidPathError, cf._Copy)

    def test_dest_block_symlink(self):
        """Do not allow writing to a symlink."""
        src = os.path.join(self.worktree, "foo.txt")
        self.touch(src)
        platform_utils.symlink("dest", os.path.join(self.topdir, "sym"))
        cf = self.CopyFile("foo.txt", "sym")
        self.assertRaises(error.ManifestInvalidPathError, cf._Copy)

    def test_dest_block_symlink_traversal(self):
        """Do not allow writing through a symlink dir."""
        src = os.path.join(self.worktree, "foo.txt")
        self.touch(src)
        platform_utils.symlink(tempfile.gettempdir(), os.path.join(self.topdir, "sym"))
        cf = self.CopyFile("foo.txt", "sym/foo.txt")
        self.assertRaises(error.ManifestInvalidPathError, cf._Copy)

    def test_src_block_copy_to_dir(self):
        """Do not allow copying to a directory."""
        src = os.path.join(self.worktree, "foo.txt")
        self.touch(src)
        os.makedirs(os.path.join(self.topdir, "dir"))
        cf = self.CopyFile("foo.txt", "dir")
        self.assertRaises(error.ManifestInvalidPathError, cf._Copy)


class LinkFile(CopyLinkTestCase):
    """Check _LinkFile handling."""

    def LinkFile(self, src, dest):
        return project._LinkFile(self.worktree, src, self.topdir, dest)

    def test_basic(self):
        """Basic test of linking a file from a project into the toplevel."""
        src = os.path.join(self.worktree, "foo.txt")
        self.touch(src)
        lf = self.LinkFile("foo.txt", "foo")
        lf._Link()
        dest = os.path.join(self.topdir, "foo")
        self.assertExists(dest)
        self.assertTrue(os.path.islink(dest))
        self.assertEqual(os.path.join("git-project", "foo.txt"), os.readlink(dest))

    def test_src_subdir(self):
        """Link to a file in a subdir of a project."""
        src = os.path.join(self.worktree, "bar", "foo.txt")
        os.makedirs(os.path.dirname(src))
        self.touch(src)
        lf = self.LinkFile("bar/foo.txt", "foo")
        lf._Link()
        self.assertExists(os.path.join(self.topdir, "foo"))

    def test_src_self(self):
        """Link to the project itself."""
        dest = os.path.join(self.topdir, "foo", "bar")
        lf = self.LinkFile(".", "foo/bar")
        lf._Link()
        self.assertExists(dest)
        self.assertEqual(os.path.join("..", "git-project"), os.readlink(dest))

    def test_dest_subdir(self):
        """Link a file to a subdir of a checkout."""
        src = os.path.join(self.worktree, "foo.txt")
        self.touch(src)
        lf = self.LinkFile("foo.txt", "sub/dir/foo/bar")
        self.assertFalse(os.path.exists(os.path.join(self.topdir, "sub")))
        lf._Link()
        self.assertExists(os.path.join(self.topdir, "sub", "dir", "foo", "bar"))

    def test_src_block_relative(self):
        """Do not allow relative symlinks."""
        BAD_SOURCES = (
            "./",
            "..",
            "../",
            "foo/.",
            "foo/./bar",
            "foo/..",
            "foo/../foo",
        )
        for src in BAD_SOURCES:
            lf = self.LinkFile(src, "foo")
            self.assertRaises(error.ManifestInvalidPathError, lf._Link)

    def test_update(self):
        """Make sure changed targets get updated."""
        dest = os.path.join(self.topdir, "sym")

        src = os.path.join(self.worktree, "foo.txt")
        self.touch(src)
        lf = self.LinkFile("foo.txt", "sym")
        lf._Link()
        self.assertEqual(os.path.join("git-project", "foo.txt"), os.readlink(dest))

        # Point the symlink somewhere else.
        os.unlink(dest)
        platform_utils.symlink(self.tempdir, dest)
        lf._Link()
        self.assertEqual(os.path.join("git-project", "foo.txt"), os.readlink(dest))


class LinkFileDirectoryTargetTests(CopyLinkTestCase):
    """Verification tests for <linkfile> with directory targets.

    Spec reference: Section 17.3 — Existing behaviors to preserve.

    The fork must not break linkfile with directory targets. When src
    is a directory, _Link() should create a symlink pointing to that
    directory relative to the dest location.
    """

    def LinkFile(self, src, dest):
        return project._LinkFile(self.worktree, src, self.topdir, dest)

    def test_spec_17_3_linkfile_directory_target_preserved(self):
        """Linkfile with directory src creates symlink to directory.

        Given: A project containing a subdirectory 'data/configs'.
        When: A linkfile links 'data/configs' to 'configs' under topdir.
        Then: A symlink is created at topdir/configs pointing to the
            directory, and the symlink target is valid.
        Spec: Section 17.3 — directory linkfile targets preserved.
        """
        # Create a directory with a file inside the project worktree.
        src_dir = os.path.join(self.worktree, "data", "configs")
        os.makedirs(src_dir)
        self.touch(os.path.join(src_dir, "settings.json"))

        lf = self.LinkFile("data/configs", "configs")
        lf._Link()

        dest = os.path.join(self.topdir, "configs")
        self.assertExists(dest)
        self.assertTrue(os.path.islink(dest))
        # The symlink target should be relative, pointing into git-project.
        link_target = os.readlink(dest)
        self.assertEqual(os.path.join("git-project", "data", "configs"), link_target)
        # The file inside the directory should be accessible through the link.
        linked_file = os.path.join(dest, "settings.json")
        self.assertTrue(
            os.path.exists(linked_file),
            f"File inside linked directory should be accessible: {linked_file}",
        )


class LinkFileAbsoluteDestTests(CopyLinkTestCase):
    """Tests for _LinkFile._Link() with absolute dest paths.

    Spec reference: Section 17.1 — Absolute Linkfile Dest.

    When dest is an absolute path, _Link() should:
    - Create parent directories at the absolute path
    - Create the symlink at the exact absolute path
    - Not use _SafeExpandPath for the dest

    When dest is relative, existing behavior is unchanged.
    """

    def LinkFile(self, src, dest):
        return project._LinkFile(self.worktree, src, self.topdir, dest)

    def test_spec_17_1_link_absolute_dest_creates_parents(self):
        """_Link() creates parent directories for absolute dest.

        Given: A _LinkFile with absolute dest in a non-existent dir tree.
        When: _Link() is called.
        Then: Parent directories are created.
        Spec: Section 17.1 — absolute dest creates parents.
        """
        src = os.path.join(self.worktree, "plugin.txt")
        self.touch(src)
        abs_dest = os.path.join(self.tempdir, "abs-out", "deep", "link")
        lf = self.LinkFile("plugin.txt", abs_dest)
        lf._Link()
        parent_dir = os.path.dirname(abs_dest)
        self.assertTrue(
            os.path.isdir(parent_dir),
            f"parent dir '{parent_dir}' should exist",
        )

    def test_spec_17_1_link_absolute_dest_creates_symlink(self):
        """_Link() creates symlink at the exact absolute dest path.

        Given: A _LinkFile with absolute dest.
        When: _Link() is called.
        Then: Symlink exists at the absolute dest path pointing to src.
        Spec: Section 17.1 — absolute dest creates symlink.
        """
        src = os.path.join(self.worktree, "plugin.txt")
        self.touch(src)
        abs_dest = os.path.join(self.tempdir, "abs-out", "link")
        lf = self.LinkFile("plugin.txt", abs_dest)
        lf._Link()
        self.assertTrue(
            os.path.islink(abs_dest),
            f"symlink should exist at '{abs_dest}'",
        )
        self.assertTrue(
            os.path.exists(abs_dest),
            f"symlink target should be resolvable at '{abs_dest}'",
        )

    def test_spec_17_1_link_relative_dest_uses_safe_expand(self):
        """_Link() uses _SafeExpandPath for relative dest (existing behavior).

        Given: A _LinkFile with relative dest.
        When: _Link() is called.
        Then: Symlink is created under topdir via _SafeExpandPath.
        Spec: Section 17.1 — relative dest backward compatibility.
        """
        src = os.path.join(self.worktree, "foo.txt")
        self.touch(src)
        lf = self.LinkFile("foo.txt", "relative-link")
        lf._Link()
        expected = os.path.join(self.topdir, "relative-link")
        self.assertExists(expected)
        self.assertTrue(
            os.path.islink(expected),
            f"relative dest should create symlink at '{expected}'",
        )

    def test_spec_17_1_link_absolute_dest_existing_parent_ok(self):
        """_Link() works when absolute dest parent directory already exists.

        Given: A _LinkFile with absolute dest in an existing directory.
        When: _Link() is called.
        Then: No error; symlink is created.
        Spec: Section 17.1 — existing parent dir no-error.
        """
        src = os.path.join(self.worktree, "plugin.txt")
        self.touch(src)
        abs_dir = os.path.join(self.tempdir, "existing-dir")
        os.makedirs(abs_dir)
        abs_dest = os.path.join(abs_dir, "link")
        lf = self.LinkFile("plugin.txt", abs_dest)
        lf._Link()
        self.assertTrue(
            os.path.islink(abs_dest),
            f"symlink should exist at '{abs_dest}'",
        )

    def test_spec_17_1_link_absolute_dest_rejects_path_traversal(self):
        """_Link() rejects absolute dest with '..' traversal components.

        Given: A _LinkFile with absolute dest containing '..'.
        When: _Link() is called.
        Then: ManifestInvalidPathError is raised.
        Spec: Section 17.1 — defense-in-depth path validation.
        """
        src = os.path.join(self.worktree, "plugin.txt")
        self.touch(src)
        abs_dest = os.path.join(self.tempdir, "abs-out", "..", "escape", "link")
        lf = self.LinkFile("plugin.txt", abs_dest)
        self.assertRaises(error.ManifestInvalidPathError, lf._Link)

    def test_spec_17_1_link_abs_dest_replaces_existing_symlink(self):
        """_Link() replaces an existing symlink at the absolute dest.

        Given: An existing symlink at the absolute dest path.
        When: _Link() is called with a different source.
        Then: The old symlink is replaced and points to the new source.
        Spec: Section 17.1 — existing symlink replacement.
        """
        src_old = os.path.join(self.worktree, "old.txt")
        src_new = os.path.join(self.worktree, "new.txt")
        self.touch(src_old)
        self.touch(src_new)
        abs_dest = os.path.join(self.tempdir, "abs-out", "link")
        # Create initial symlink via _Link with old source.
        lf_old = self.LinkFile("old.txt", abs_dest)
        lf_old._Link()
        self.assertTrue(os.path.islink(abs_dest))
        # Replace with new source.
        lf_new = self.LinkFile("new.txt", abs_dest)
        lf_new._Link()
        self.assertTrue(
            os.path.islink(abs_dest),
            f"symlink should still exist at '{abs_dest}'",
        )
        target = os.readlink(abs_dest)
        resolved = os.path.join(os.path.dirname(abs_dest), target)
        self.assertTrue(
            os.path.samefile(resolved, src_new),
            f"symlink should resolve to new source, got '{resolved}'",
        )

    def test_spec_17_1_link_abs_dest_deeply_nested_parents(self):
        """_Link() creates deeply nested parent directories for absolute dest.

        Given: An absolute dest with many levels of non-existent directories.
        When: _Link() is called.
        Then: All intermediate directories are created and symlink exists.
        Spec: Section 17.1 — deeply nested directory creation.
        """
        src = os.path.join(self.worktree, "deep.txt")
        self.touch(src)
        abs_dest = os.path.join(self.tempdir, "a", "b", "c", "d", "e", "f", "link")
        lf = self.LinkFile("deep.txt", abs_dest)
        lf._Link()
        self.assertTrue(
            os.path.isdir(os.path.dirname(abs_dest)),
            "all intermediate parent directories should be created",
        )
        self.assertTrue(
            os.path.islink(abs_dest),
            f"symlink should exist at deeply nested path '{abs_dest}'",
        )

    def test_spec_17_1_link_abs_dest_trailing_slash(self):
        """_Link() handles absolute dest with trailing slash gracefully.

        Given: An absolute dest path ending with os.sep.
        When: _Link() is called.
        Then: The trailing slash is normalized and the symlink is created.
        Spec: Section 17.1 — trailing slash edge case.
        """
        src = os.path.join(self.worktree, "trail.txt")
        self.touch(src)
        # normpath strips trailing slash, so the link is created at the
        # normalized path.
        raw_dest = os.path.join(self.tempdir, "trail-out", "link") + os.sep
        normalized = os.path.normpath(raw_dest)
        lf = self.LinkFile("trail.txt", raw_dest)
        lf._Link()
        self.assertTrue(
            os.path.islink(normalized),
            f"symlink should exist at normalized path '{normalized}'",
        )


@pytest.mark.unit
class LinkFileExcludeTests(CopyLinkTestCase):
    """Tests for the exclude attribute on <linkfile>."""

    def LinkFile(self, src, dest, exclude=None):
        return project._LinkFile(self.worktree, src, self.topdir, dest, exclude=exclude)

    def _make_src_dir(self, name, children):
        """Create a source directory with the given children (files)."""
        src_dir = os.path.join(self.worktree, name)
        os.makedirs(src_dir, exist_ok=True)
        for child in children:
            child_path = os.path.join(src_dir, child)
            if os.path.basename(child) == child:
                self.touch(child_path)
            else:
                os.makedirs(os.path.dirname(child_path), exist_ok=True)
                self.touch(child_path)
        return src_dir

    def test_exclude_creates_real_directory(self):
        self._make_src_dir("pkg", ["a.py", "b.py"])
        dest = os.path.join(self.topdir, "linked-pkg")
        lf = self.LinkFile("pkg", dest, exclude="b.py")
        lf._Link()
        self.assertTrue(os.path.isdir(dest))
        self.assertFalse(os.path.islink(dest))

    def test_exclude_links_non_excluded_children(self):
        self._make_src_dir("pkg", ["a.py", "b.py", "c.py"])
        dest = os.path.join(self.topdir, "linked-pkg")
        lf = self.LinkFile("pkg", dest, exclude="b.py")
        lf._Link()
        self.assertTrue(os.path.islink(os.path.join(dest, "a.py")))
        self.assertTrue(os.path.islink(os.path.join(dest, "c.py")))

    def test_exclude_skips_excluded_children(self):
        self._make_src_dir("pkg", ["a.py", "tests"])
        dest = os.path.join(self.topdir, "linked-pkg")
        lf = self.LinkFile("pkg", dest, exclude="tests")
        lf._Link()
        self.assertFalse(os.path.exists(os.path.join(dest, "tests")))

    def test_exclude_multiple_comma_separated(self):
        self._make_src_dir("pkg", ["a.py", "tests", "docs", "__pycache__"])
        dest = os.path.join(self.topdir, "linked-pkg")
        lf = self.LinkFile("pkg", dest, exclude="tests,docs,__pycache__")
        lf._Link()
        self.assertTrue(os.path.islink(os.path.join(dest, "a.py")))
        self.assertFalse(os.path.exists(os.path.join(dest, "tests")))
        self.assertFalse(os.path.exists(os.path.join(dest, "docs")))
        self.assertFalse(os.path.exists(os.path.join(dest, "__pycache__")))

    def test_exclude_with_whitespace_in_csv(self):
        self._make_src_dir("pkg", ["a.py", "tests", "docs"])
        dest = os.path.join(self.topdir, "linked-pkg")
        lf = self.LinkFile("pkg", dest, exclude=" tests , docs ")
        lf._Link()
        self.assertTrue(os.path.islink(os.path.join(dest, "a.py")))
        self.assertFalse(os.path.exists(os.path.join(dest, "tests")))
        self.assertFalse(os.path.exists(os.path.join(dest, "docs")))

    def test_exclude_on_file_src_raises_error(self):
        src = os.path.join(self.worktree, "file.txt")
        self.touch(src)
        dest = os.path.join(self.topdir, "linked-file")
        lf = self.LinkFile("file.txt", dest, exclude="something")
        from kanon_cli.repo.error import ManifestInvalidPathError

        with self.assertRaises(ManifestInvalidPathError):
            lf._Link()

    def test_exclude_empty_string_behaves_as_no_exclude(self):
        self._make_src_dir("pkg", ["a.py", "b.py"])
        dest = os.path.join(self.topdir, "linked-pkg")
        lf = self.LinkFile("pkg", dest, exclude="")
        lf._Link()
        # Empty exclude -> single symlink to directory
        self.assertTrue(os.path.islink(dest))

    def test_exclude_with_absolute_dest(self):
        self._make_src_dir("pkg", ["a.py", "tests"])
        abs_dest = os.path.join(self.tempdir, "abs-out", "linked-pkg")
        lf = self.LinkFile("pkg", abs_dest, exclude="tests")
        lf._Link()
        self.assertTrue(os.path.isdir(abs_dest))
        self.assertFalse(os.path.islink(abs_dest))
        self.assertTrue(os.path.islink(os.path.join(abs_dest, "a.py")))
        self.assertFalse(os.path.exists(os.path.join(abs_dest, "tests")))

    def test_exclude_nonexistent_entry_no_error(self):
        self._make_src_dir("pkg", ["a.py"])
        dest = os.path.join(self.topdir, "linked-pkg")
        lf = self.LinkFile("pkg", dest, exclude="nonexistent")
        lf._Link()
        self.assertTrue(os.path.islink(os.path.join(dest, "a.py")))

    def test_no_exclude_preserves_directory_symlink(self):
        self._make_src_dir("pkg", ["a.py", "b.py"])
        dest = os.path.join(self.topdir, "linked-pkg")
        lf = self.LinkFile("pkg", dest)
        lf._Link()
        self.assertTrue(os.path.islink(dest))

    def test_exclude_with_glob_src_raises_error(self):
        self._make_src_dir("pkg", ["a.py"])
        dest = os.path.join(self.topdir, "linked-pkg")
        lf = self.LinkFile("pk*", dest, exclude="something")
        from kanon_cli.repo.error import ManifestInvalidPathError

        with self.assertRaises(ManifestInvalidPathError):
            lf._Link()

    def test_exclude_auto_skips_dot_git(self):
        src_dir = self._make_src_dir("pkg", ["a.py"])
        os.makedirs(os.path.join(src_dir, ".git"))
        dest = os.path.join(self.topdir, "linked-pkg")
        lf = self.LinkFile("pkg", dest, exclude="something")
        lf._Link()
        self.assertFalse(os.path.exists(os.path.join(dest, ".git")))
        self.assertTrue(os.path.islink(os.path.join(dest, "a.py")))

    def test_exclude_auto_skips_dot_repo(self):
        src_dir = self._make_src_dir("pkg", ["a.py"])
        os.makedirs(os.path.join(src_dir, ".repo"))
        os.makedirs(os.path.join(src_dir, ".repoconfig"))
        dest = os.path.join(self.topdir, "linked-pkg")
        lf = self.LinkFile("pkg", dest, exclude="something")
        lf._Link()
        self.assertFalse(os.path.exists(os.path.join(dest, ".repo")))
        self.assertFalse(os.path.exists(os.path.join(dest, ".repoconfig")))
        self.assertTrue(os.path.islink(os.path.join(dest, "a.py")))

    def test_exclude_auto_skips_dot_packages(self):
        src_dir = self._make_src_dir("pkg", ["a.py"])
        os.makedirs(os.path.join(src_dir, ".packages"))
        dest = os.path.join(self.topdir, "linked-pkg")
        lf = self.LinkFile("pkg", dest, exclude="something")
        lf._Link()
        self.assertFalse(os.path.exists(os.path.join(dest, ".packages")))
        self.assertTrue(os.path.islink(os.path.join(dest, "a.py")))

    def test_exclude_links_other_hidden_files(self):
        src_dir = self._make_src_dir("pkg", ["a.py"])
        self.touch(os.path.join(src_dir, ".config"))
        self.touch(os.path.join(src_dir, ".env"))
        dest = os.path.join(self.topdir, "linked-pkg")
        lf = self.LinkFile("pkg", dest, exclude="something")
        lf._Link()
        self.assertTrue(os.path.islink(os.path.join(dest, ".config")))
        self.assertTrue(os.path.islink(os.path.join(dest, ".env")))


_FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def _load_fixture():
    """Load version constraint test data from fixture file."""
    fixture_path = os.path.join(_FIXTURES_DIR, "version_constraints_data.json")
    with open(fixture_path) as f:
        return json.load(f)


_VC_DATA = _load_fixture()
_GRI_DATA = _VC_DATA["get_revision_id"]


def _build_ls_remote_output(tags):
    """Build mock git ls-remote --tags output from a list of tag refs.

    Args:
        tags: List of tag ref strings.

    Returns:
        String formatted like git ls-remote output (SHA\\tref per line).
    """
    lines = []
    for i, tag in enumerate(tags):
        lines.append(f"{'%040x' % i}\t{tag}")
    return "\n".join(lines)


@pytest.mark.unit
class TestGetRevisionIdVersionConstraints:
    """Tests for _ResolveVersionConstraint() on the Project class.

    Spec reference: Section 17.2 -- version constraint resolution.

    _ResolveVersionConstraint() detects PEP 440 constraints in
    revisionExpr, runs git ls-remote to get available tags, resolves
    the constraint, and mutates revisionExpr to the exact tag.
    """

    def test_spec_17_2_constraint_detected_and_resolved(self):
        """_ResolveVersionConstraint mutates revisionExpr to resolved tag.

        Given: A project with revisionExpr containing a PEP 440 constraint.
        When: _ResolveVersionConstraint() is called.
        Then: revisionExpr is mutated to the resolved exact tag.
        Spec: Section 17.2 -- constraint detection and resolution.
        """
        from unittest.mock import MagicMock, patch

        proj = MagicMock()
        proj.revisionExpr = _GRI_DATA["constraint_revision"]
        proj.name = "test-project"
        proj.remote = MagicMock()
        proj.remote.url = "https://example.com/repo.git"
        proj._constraint_resolved = False

        ls_output = _build_ls_remote_output(_GRI_DATA["remote_tags"])

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=ls_output, stderr="")
            project.Project._ResolveVersionConstraint(proj)

        assert proj.revisionExpr == _GRI_DATA["resolved_tag"], (
            f"expected revisionExpr to be '{_GRI_DATA['resolved_tag']}', got '{proj.revisionExpr}'"
        )

    def test_spec_17_2_non_constraint_passthrough(self):
        """Non-constraint revisionExpr is not modified.

        Given: A project with revisionExpr "main" (not a constraint).
        When: _ResolveVersionConstraint() is called.
        Then: revisionExpr remains unchanged, subprocess.run is not called.
        Spec: Section 17.2 -- non-constraint passthrough.
        """
        from unittest.mock import MagicMock, patch

        proj = MagicMock()
        proj.revisionExpr = _GRI_DATA["non_constraint_revision"]
        proj.name = "test-project"
        proj._constraint_resolved = False

        with patch("subprocess.run") as mock_run:
            project.Project._ResolveVersionConstraint(proj)
            mock_run.assert_not_called()

        assert proj.revisionExpr == _GRI_DATA["non_constraint_revision"], (
            "non-constraint revisionExpr should remain unchanged"
        )

    def test_spec_17_2_none_revision_noop(self):
        """revisionExpr=None is a no-op.

        Given: A project with revisionExpr set to None.
        When: _ResolveVersionConstraint() is called.
        Then: Nothing happens, subprocess.run is not called.
        Spec: Section 17.2 -- None revisionExpr no-op.
        """
        from unittest.mock import MagicMock, patch

        proj = MagicMock()
        proj.revisionExpr = None
        proj.name = "test-project"
        proj._constraint_resolved = False

        with patch("subprocess.run") as mock_run:
            project.Project._ResolveVersionConstraint(proj)
            mock_run.assert_not_called()

        assert proj.revisionExpr is None, "revisionExpr should remain None"

    def test_spec_17_2_ls_remote_failure_raises(self):
        """ls-remote failure raises ManifestInvalidRevisionError.

        Given: A project with a constraint revisionExpr.
        When: git ls-remote returns a non-zero exit code.
        Then: ManifestInvalidRevisionError is raised with diagnostic message.
        Spec: Section 17.2 -- ls-remote failure handling.
        """
        from unittest.mock import MagicMock, patch

        proj = MagicMock()
        proj.revisionExpr = _GRI_DATA["constraint_revision"]
        proj.name = "test-project"
        proj.remote = MagicMock()
        proj.remote.url = "https://example.com/repo.git"
        proj._constraint_resolved = False

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=128, stdout="", stderr="fatal: error")
            with pytest.raises(
                error.ManifestInvalidRevisionError,
                match="failed to list remote tags",
            ):
                project.Project._ResolveVersionConstraint(proj)

    def test_spec_17_2_no_matching_tags_raises(self):
        """No matching tags raises ManifestInvalidRevisionError.

        Given: A project with a constraint that matches no available tags.
        When: _ResolveVersionConstraint() is called.
        Then: ManifestInvalidRevisionError is raised from
            resolve_version_constraint.
        Spec: Section 17.2 -- error on no match.
        """
        from unittest.mock import MagicMock, patch

        proj = MagicMock()
        proj.revisionExpr = _GRI_DATA["no_match_constraint"]
        proj.name = "test-project"
        proj.remote = MagicMock()
        proj.remote.url = "https://example.com/repo.git"
        proj._constraint_resolved = False

        ls_output = _build_ls_remote_output(_GRI_DATA["remote_tags"])

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=ls_output, stderr="")
            with pytest.raises(error.ManifestInvalidRevisionError):
                project.Project._ResolveVersionConstraint(proj)

    def test_spec_17_2_wildcard_resolves_to_latest(self):
        """Wildcard constraint resolves to the latest tag.

        Given: A project with revisionExpr containing wildcard (*).
        When: _ResolveVersionConstraint() is called.
        Then: revisionExpr is mutated to the latest tag.
        Spec: Section 17.2 -- wildcard constraint resolution.
        """
        from unittest.mock import MagicMock, patch

        proj = MagicMock()
        proj.revisionExpr = _GRI_DATA["wildcard_constraint_revision"]
        proj.name = "test-project"
        proj.remote = MagicMock()
        proj.remote.url = "https://example.com/repo.git"
        proj._constraint_resolved = False

        ls_output = _build_ls_remote_output(_GRI_DATA["remote_tags"])

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=ls_output, stderr="")
            project.Project._ResolveVersionConstraint(proj)

        assert proj.revisionExpr == _GRI_DATA["wildcard_resolved_tag"], (
            f"wildcard should resolve to '{_GRI_DATA['wildcard_resolved_tag']}', got '{proj.revisionExpr}'"
        )

    def test_spec_17_2_range_constraint_resolves(self):
        """Range constraint resolves to correct tag.

        Given: A project with revisionExpr containing a range constraint.
        When: _ResolveVersionConstraint() is called with tags from fixture.
        Then: revisionExpr is mutated to the highest tag within the range.
        Spec: Section 17.2 -- range constraint resolution.
        """
        from unittest.mock import MagicMock, patch

        range_data = _VC_DATA["integration"]["range"]
        proj = MagicMock()
        proj.revisionExpr = range_data["revision"]
        proj.name = "test-project"
        proj.remote = MagicMock()
        proj.remote.url = "https://example.com/repo.git"
        proj._constraint_resolved = False

        ls_output = _build_ls_remote_output(_VC_DATA["integration"]["available_tags"])

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=ls_output, stderr="")
            project.Project._ResolveVersionConstraint(proj)

        assert proj.revisionExpr == range_data["expected_tag"], (
            f"range constraint should resolve to '{range_data['expected_tag']}', got '{proj.revisionExpr}'"
        )


_INTEG_DATA = _VC_DATA["integration"]


class TestGetRevisionIdIntegration:
    """Integration tests for _ResolveVersionConstraint via fixture data.

    Spec reference: Section 5.5 and 17.2.

    These tests exercise _ResolveVersionConstraint() with the real
    version_constraints module (no mocking of is_version_constraint or
    resolve_version_constraint) against mock git ls-remote output built
    from fixture tag sets. Each constraint type (compatible release,
    wildcard, range) is parameterized to verify correct resolution.
    """

    @pytest.mark.parametrize(
        "constraint_type",
        [
            pytest.param(
                "compatible_release",
                id="compatible_release_~=1.2.0_resolves_to_1.2.7",
            ),
            pytest.param(
                "wildcard",
                id="wildcard_*_resolves_to_latest",
            ),
            pytest.param(
                "range",
                id="range_>=1.0.0,<2.0.0_resolves_to_1.3.0",
            ),
        ],
    )
    def test_spec_5_5_integration_constraint_resolution(self, constraint_type):
        """Integration: PEP 440 constraint resolves to correct tag.

        Given: Mock ls-remote output from fixture data and a constraint.
        When: _ResolveVersionConstraint() runs with real version_constraints.
        Then: revisionExpr is mutated to the correct resolved tag.
        Spec: Section 5.5 -- constraint types and resolution behavior.
        """
        from unittest.mock import MagicMock, patch

        case = _INTEG_DATA[constraint_type]
        proj = MagicMock()
        proj.revisionExpr = case["revision"]
        proj.name = "test-project"
        proj.remote = MagicMock()
        proj.remote.url = "https://example.com/repo.git"
        proj._constraint_resolved = False

        ls_output = _build_ls_remote_output(_INTEG_DATA["available_tags"])

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=ls_output, stderr="")
            project.Project._ResolveVersionConstraint(proj)

        assert proj.revisionExpr == case["expected_tag"], (
            f"{constraint_type} constraint '{case['revision']}' should resolve to "
            f"'{case['expected_tag']}', got '{proj.revisionExpr}'"
        )


class MigrateWorkTreeTests(unittest.TestCase):
    """Check _MigrateOldWorkTreeGitDir handling."""

    _SYMLINKS = {
        "config",
        "description",
        "hooks",
        "info",
        "logs",
        "objects",
        "packed-refs",
        "refs",
        "rr-cache",
        "shallow",
        "svn",
    }
    _FILES = {
        "COMMIT_EDITMSG",
        "FETCH_HEAD",
        "HEAD",
        "index",
        "ORIG_HEAD",
        "unknown-file-should-be-migrated",
    }
    _CLEAN_FILES = {
        "a-vim-temp-file~",
        "#an-emacs-temp-file#",
    }

    @classmethod
    @contextlib.contextmanager
    def _simple_layout(cls):
        """Create a simple repo client checkout to test against."""
        with tempfile.TemporaryDirectory() as tempdir:
            tempdir = Path(tempdir)

            gitdir = tempdir / ".repo/projects/src/test.git"
            gitdir.mkdir(parents=True)
            cmd = ["git", "init", "--bare", str(gitdir)]
            subprocess.check_call(cmd)

            dotgit = tempdir / "src/test/.git"
            dotgit.mkdir(parents=True)
            for name in cls._SYMLINKS:
                (dotgit / name).symlink_to(f"../../../.repo/projects/src/test.git/{name}")
            for name in cls._FILES | cls._CLEAN_FILES:
                (dotgit / name).write_text(name)

            yield tempdir

    def test_standard(self):
        """Migrate a standard checkout that we expect."""
        with self._simple_layout() as tempdir:
            dotgit = tempdir / "src/test/.git"
            project.Project._MigrateOldWorkTreeGitDir(str(dotgit))

            # Make sure the dir was transformed into a symlink.
            self.assertTrue(dotgit.is_symlink())
            self.assertEqual(
                os.readlink(dotgit),
                os.path.normpath("../../.repo/projects/src/test.git"),
            )

            # Make sure files were moved over.
            gitdir = tempdir / ".repo/projects/src/test.git"
            for name in self._FILES:
                self.assertEqual(name, (gitdir / name).read_text())
            # Make sure files were removed.
            for name in self._CLEAN_FILES:
                self.assertFalse((gitdir / name).exists())

    def test_unknown(self):
        """A checkout with unknown files should abort."""
        with self._simple_layout() as tempdir:
            dotgit = tempdir / "src/test/.git"
            (tempdir / ".repo/projects/src/test.git/random-file").write_text("one")
            (dotgit / "random-file").write_text("two")
            with self.assertRaises(error.GitError):
                project.Project._MigrateOldWorkTreeGitDir(str(dotgit))

            # Make sure no content was actually changed.
            self.assertTrue(dotgit.is_dir())
            for name in self._FILES:
                self.assertTrue((dotgit / name).is_file())
            for name in self._CLEAN_FILES:
                self.assertTrue((dotgit / name).is_file())
            for name in self._SYMLINKS:
                self.assertTrue((dotgit / name).is_symlink())


class ManifestPropertiesFetchedCorrectly(unittest.TestCase):
    """Ensure properties are fetched properly."""

    def setUpManifest(self, tempdir):
        repodir = os.path.join(tempdir, ".repo")
        manifest_dir = os.path.join(repodir, "manifests")
        manifest_file = os.path.join(repodir, manifest_xml.MANIFEST_FILE_NAME)
        os.mkdir(repodir)
        os.mkdir(manifest_dir)
        manifest = manifest_xml.XmlManifest(repodir, manifest_file)

        return project.ManifestProject(manifest, "test/manifest", os.path.join(tempdir, ".git"), tempdir)

    def test_manifest_config_properties(self):
        """Test we are fetching the manifest config properties correctly."""

        with TempGitTree() as tempdir:
            fakeproj = self.setUpManifest(tempdir)

            # Set property using the expected Set method, then ensure
            # the porperty functions are using the correct Get methods.
            fakeproj.config.SetString("manifest.standalone", "https://chicken/manifest.git")
            self.assertEqual(fakeproj.standalone_manifest_url, "https://chicken/manifest.git")

            fakeproj.config.SetString("manifest.groups", "test-group, admin-group")
            self.assertEqual(fakeproj.manifest_groups, "test-group, admin-group")

            fakeproj.config.SetString("repo.reference", "mirror/ref")
            self.assertEqual(fakeproj.reference, "mirror/ref")

            fakeproj.config.SetBoolean("repo.dissociate", False)
            self.assertFalse(fakeproj.dissociate)

            fakeproj.config.SetBoolean("repo.archive", False)
            self.assertFalse(fakeproj.archive)

            fakeproj.config.SetBoolean("repo.mirror", False)
            self.assertFalse(fakeproj.mirror)

            fakeproj.config.SetBoolean("repo.worktree", False)
            self.assertFalse(fakeproj.use_worktree)

            fakeproj.config.SetBoolean("repo.clonebundle", False)
            self.assertFalse(fakeproj.clone_bundle)

            fakeproj.config.SetBoolean("repo.submodules", False)
            self.assertFalse(fakeproj.submodules)

            fakeproj.config.SetBoolean("repo.git-lfs", False)
            self.assertFalse(fakeproj.git_lfs)

            fakeproj.config.SetBoolean("repo.superproject", False)
            self.assertFalse(fakeproj.use_superproject)

            fakeproj.config.SetBoolean("repo.partialclone", False)
            self.assertFalse(fakeproj.partial_clone)

            fakeproj.config.SetString("repo.depth", "48")
            self.assertEqual(fakeproj.depth, 48)

            fakeproj.config.SetString("repo.depth", "invalid_depth")
            self.assertEqual(fakeproj.depth, None)

            fakeproj.config.SetString("repo.clonefilter", "blob:limit=10M")
            self.assertEqual(fakeproj.clone_filter, "blob:limit=10M")

            fakeproj.config.SetString("repo.partialcloneexclude", "third_party/big_repo")
            self.assertEqual(fakeproj.partial_clone_exclude, "third_party/big_repo")

            fakeproj.config.SetString("manifest.platform", "auto")
            self.assertEqual(fakeproj.manifest_platform, "auto")


@pytest.mark.unit
class CopyFileLinkFileDataStructureTests(unittest.TestCase):
    """Tests for copyfile/linkfile data structure changes (fork feature).

    The fork changed _CopyFile and _LinkFile from NamedTuple to regular
    classes, and storage from dict to list.
    """

    def test_copyfile_is_mutable_class(self):
        """_CopyFile should be a regular class, not a NamedTuple."""
        cf = project._CopyFile("/worktree", "src.txt", "/topdir", "dest.txt")
        # Regular classes allow attribute modification; NamedTuples don't
        cf.src = "new_src.txt"
        self.assertEqual(cf.src, "new_src.txt")

    def test_linkfile_is_mutable_class(self):
        """_LinkFile should be a regular class, not a NamedTuple."""
        lf = project._LinkFile("/worktree", "src.txt", "/topdir", "dest.txt")
        lf.src = "new_src.txt"
        self.assertEqual(lf.src, "new_src.txt")


# Additional coverage tests appended below


@pytest.mark.unit
class TestLwriteFunction:
    """Test the _lwrite function."""

    def test_lwrite_creates_file_with_content(self):
        """Test that _lwrite creates a file with the specified content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.txt")
            content = "test content\nline2"
            project._lwrite(path, content)

            assert os.path.exists(path)
            with open(path, "r") as f:
                assert f.read() == content

    def test_lwrite_uses_unix_line_endings(self):
        """Test that _lwrite uses Unix line endings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.txt")
            content = "line1\nline2\n"
            project._lwrite(path, content)

            # Read in binary mode to check line endings
            with open(path, "rb") as f:
                raw_content = f.read()
            assert b"\r\n" not in raw_content
            assert b"\n" in raw_content

    def test_lwrite_replaces_existing_file(self):
        """Test that _lwrite replaces an existing file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.txt")
            # Create initial file
            with open(path, "w") as f:
                f.write("old content")

            # Overwrite with _lwrite
            new_content = "new content"
            project._lwrite(path, new_content)

            with open(path, "r") as f:
                assert f.read() == new_content

    def test_lwrite_cleans_up_lock_on_error(self):
        """Test that _lwrite removes lock file on error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.txt")
            lock_path = path + ".lock"

            with mock.patch("kanon_cli.repo.platform_utils.rename", side_effect=OSError("Rename failed")):
                with pytest.raises(OSError):
                    project._lwrite(path, "content")

            # Lock file should be cleaned up
            assert not os.path.exists(lock_path)


@pytest.mark.unit
class TestSyncNetworkHalfResult:
    """Test SyncNetworkHalfResult NamedTuple."""

    def test_success_property_true_when_no_error(self):
        """Test success property returns True when error is None."""
        result = project.SyncNetworkHalfResult(remote_fetched=True, error=None)
        assert result.success is True

    def test_success_property_false_when_error_present(self):
        """Test success property returns False when error is present."""
        err = Exception("test error")
        result = project.SyncNetworkHalfResult(remote_fetched=False, error=err)
        assert result.success is False

    def test_remote_fetched_attribute(self):
        """Test remote_fetched attribute."""
        result = project.SyncNetworkHalfResult(remote_fetched=True)
        assert result.remote_fetched is True

        result2 = project.SyncNetworkHalfResult(remote_fetched=False)
        assert result2.remote_fetched is False

    def test_error_attribute(self):
        """Test error attribute."""
        err = ValueError("test error")
        result = project.SyncNetworkHalfResult(remote_fetched=True, error=err)
        assert result.error is err


@pytest.mark.unit
class TestDeleteWorktreeError:
    """Test DeleteWorktreeError exception class."""

    def test_init_without_aggregate_errors(self):
        """Test DeleteWorktreeError without aggregate_errors."""
        err = project.DeleteWorktreeError("Test error")
        assert str(err) == "Test error"
        assert err.aggregate_errors == []

    def test_init_with_aggregate_errors(self):
        """Test DeleteWorktreeError with aggregate_errors."""
        errors = [ValueError("error1"), IOError("error2")]
        err = project.DeleteWorktreeError("Test error", aggregate_errors=errors)
        assert err.aggregate_errors == errors

    def test_init_with_none_aggregate_errors(self):
        """Test DeleteWorktreeError with None aggregate_errors."""
        err = project.DeleteWorktreeError("Test error", aggregate_errors=None)
        assert err.aggregate_errors == []


@pytest.mark.unit
class TestCopyFileClassExtended:
    """Test _CopyFile class additional scenarios."""

    def test_copyfile_init(self):
        """Test _CopyFile initialization."""
        cf = project._CopyFile("/git/worktree", "src.txt", "/topdir", "dest.txt")
        assert cf.git_worktree == "/git/worktree"
        assert cf.src == "src.txt"
        assert cf.topdir == "/topdir"
        assert cf.dest == "dest.txt"

    def test_copy_handles_ioerror(self):
        """Test _Copy handles IOError gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = os.path.join(tmpdir, "worktree")
            topdir = os.path.join(tmpdir, "topdir")
            os.makedirs(worktree)
            os.makedirs(topdir)

            # Create source file
            src_file = os.path.join(worktree, "src.txt")
            with open(src_file, "w") as f:
                f.write("content")

            cf = project._CopyFile(worktree, "src.txt", topdir, "dest.txt")

            # Mock shutil.copy to raise IOError
            with mock.patch("shutil.copy", side_effect=IOError("Copy failed")):
                # Should not raise, just log error
                cf._Copy()

    def test_copy_creates_dest_directory(self):
        """Test _Copy creates destination directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = os.path.join(tmpdir, "worktree")
            topdir = os.path.join(tmpdir, "topdir")
            os.makedirs(worktree)
            os.makedirs(topdir)

            # Create source file
            src_file = os.path.join(worktree, "src.txt")
            with open(src_file, "w") as f:
                f.write("content")

            # Destination in subdirectory that doesn't exist
            cf = project._CopyFile(worktree, "src.txt", topdir, "subdir/dest.txt")
            cf._Copy()

            dest_file = os.path.join(topdir, "subdir", "dest.txt")
            assert os.path.exists(dest_file)
            with open(dest_file, "r") as f:
                assert f.read() == "content"

    def test_copy_raises_error_for_directory_source(self):
        """Test _Copy raises error when source is a directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = os.path.join(tmpdir, "worktree")
            topdir = os.path.join(tmpdir, "topdir")
            os.makedirs(worktree)
            os.makedirs(topdir)

            # Create source directory
            src_dir = os.path.join(worktree, "srcdir")
            os.makedirs(src_dir)

            cf = project._CopyFile(worktree, "srcdir", topdir, "dest.txt")

            with pytest.raises(
                error.ManifestInvalidPathError,
                match="copying from directory not supported",
            ):
                cf._Copy()

    def test_copy_raises_error_for_directory_dest(self):
        """Test _Copy raises error when dest is a directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = os.path.join(tmpdir, "worktree")
            topdir = os.path.join(tmpdir, "topdir")
            os.makedirs(worktree)
            os.makedirs(topdir)

            # Create source file
            src_file = os.path.join(worktree, "src.txt")
            with open(src_file, "w") as f:
                f.write("content")

            # Create dest as directory
            dest_dir = os.path.join(topdir, "destdir")
            os.makedirs(dest_dir)

            cf = project._CopyFile(worktree, "src.txt", topdir, "destdir")

            with pytest.raises(
                error.ManifestInvalidPathError,
                match="copying to directory not allowed",
            ):
                cf._Copy()


@pytest.mark.unit
class TestLinkFileClassExtended:
    """Test _LinkFile class additional scenarios."""

    def test_linkfile_init(self):
        """Test _LinkFile initialization."""
        lf = project._LinkFile("/git/worktree", "src.txt", "/topdir", "dest.txt")
        assert lf.git_worktree == "/git/worktree"
        assert lf.src == "src.txt"
        assert lf.topdir == "/topdir"
        assert lf.dest == "dest.txt"

    def test_link_raises_oserror_with_context(self):
        """Test _Link propagates OSError with source and destination context.

        The old behavior silently swallowed OSError. The fix requires that any
        OSError from symlink creation propagates to the caller with path context.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = os.path.join(tmpdir, "worktree")
            topdir = os.path.join(tmpdir, "topdir")
            os.makedirs(worktree)
            os.makedirs(topdir)

            src_file = os.path.join(worktree, "src.txt")
            with open(src_file, "w") as f:
                f.write("content")

            lf = project._LinkFile(worktree, "src.txt", topdir, "dest.txt")

            with mock.patch("kanon_cli.repo.platform_utils.symlink", side_effect=OSError("Link failed")):
                with pytest.raises(OSError) as exc_info:
                    lf._Link()

            assert "src.txt" in str(exc_info.value), (
                f"Error message must include the source path. Got: {exc_info.value!r}"
            )
            assert "dest.txt" in str(exc_info.value), (
                f"Error message must include the destination path. Got: {exc_info.value!r}"
            )

    def test_link_removes_existing_file_before_linking(self):
        """Test _Link removes existing file before creating symlink."""
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = os.path.join(tmpdir, "worktree")
            topdir = os.path.join(tmpdir, "topdir")
            os.makedirs(worktree)
            os.makedirs(topdir)

            # Create source file
            src_file = os.path.join(worktree, "src.txt")
            with open(src_file, "w") as f:
                f.write("content")

            # Create existing dest file
            dest_file = os.path.join(topdir, "dest.txt")
            with open(dest_file, "w") as f:
                f.write("old")

            lf = project._LinkFile(worktree, "src.txt", topdir, "dest.txt")
            lf._Link()

            # Verify it's now a symlink
            assert os.path.islink(dest_file)

    def test_link_creates_dest_directory(self):
        """Test _Link creates destination directory if it doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = os.path.join(tmpdir, "worktree")
            topdir = os.path.join(tmpdir, "topdir")
            os.makedirs(worktree)
            os.makedirs(topdir)

            # Create source file
            src_file = os.path.join(worktree, "src.txt")
            with open(src_file, "w") as f:
                f.write("content")

            # Destination in subdirectory that doesn't exist
            lf = project._LinkFile(worktree, "src.txt", topdir, "subdir/dest.txt")
            lf._Link()

            dest_file = os.path.join(topdir, "subdir", "dest.txt")
            assert os.path.islink(dest_file)

    def test_link_absolute_dest_creates_parents(self):
        """Test _Link with absolute dest creates parent directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = os.path.join(tmpdir, "worktree")
            os.makedirs(worktree)

            # Create source file
            src_file = os.path.join(worktree, "src.txt")
            with open(src_file, "w") as f:
                f.write("content")

            # Absolute destination
            abs_dest = os.path.join(tmpdir, "absolute", "nested", "dest.txt")

            lf = project._LinkFile(worktree, "src.txt", "/unused", abs_dest)
            lf._Link()

            assert os.path.islink(abs_dest)

    def test_link_absolute_dest_rejects_path_traversal(self):
        """Test _Link with absolute dest rejects path traversal."""
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = os.path.join(tmpdir, "worktree")
            os.makedirs(worktree)

            # Absolute destination with ..
            abs_dest = "/tmp/../etc/passwd"

            lf = project._LinkFile(worktree, "src.txt", "/unused", abs_dest)

            with pytest.raises(
                error.ManifestInvalidPathError,
                match='".." not allowed in absolute dest',
            ):
                lf._Link()

    def test_link_wildcard_source(self):
        """Test _Link with wildcard source."""
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = os.path.join(tmpdir, "worktree")
            topdir = os.path.join(tmpdir, "topdir")
            os.makedirs(worktree)
            os.makedirs(topdir)

            # Create multiple source files
            for i in range(3):
                src_file = os.path.join(worktree, f"file{i}.txt")
                with open(src_file, "w") as f:
                    f.write(f"content{i}")

            # Destination directory
            dest_dir = os.path.join(topdir, "destdir")
            os.makedirs(dest_dir)

            lf = project._LinkFile(worktree, "*.txt", topdir, "destdir")
            lf._Link()

            # Verify all files are linked
            for i in range(3):
                dest_file = os.path.join(dest_dir, f"file{i}.txt")
                assert os.path.islink(dest_file)

    def test_link_wildcard_dest_not_directory_raises_error(self):
        """Test _Link with wildcard when dest is not a directory raises an error.

        Bug 20 fix: when the glob destination is an existing file (not a
        directory), _Link() must raise ManifestInvalidPathError instead of
        logging and continuing silently.
        """
        import pytest

        from kanon_cli.repo.error import ManifestInvalidPathError

        with tempfile.TemporaryDirectory() as tmpdir:
            worktree = os.path.join(tmpdir, "worktree")
            topdir = os.path.join(tmpdir, "topdir")
            os.makedirs(worktree)
            os.makedirs(topdir)

            # Create source file
            src_file = os.path.join(worktree, "file.txt")
            with open(src_file, "w") as f:
                f.write("content")

            # Create dest as file -- triggers Bug 20 condition
            dest_file = os.path.join(topdir, "destfile")
            with open(dest_file, "w") as f:
                f.write("existing")

            lf = project._LinkFile(worktree, "*.txt", topdir, "destfile")
            with pytest.raises(ManifestInvalidPathError) as exc_info:
                lf._Link()
            assert dest_file in str(exc_info.value) or "destfile" in str(exc_info.value), (
                f"Expected error message to include dest path, got: {exc_info.value!r}"
            )


@pytest.mark.unit
class TestHelperFunctions:
    """Test helper functions."""

    def test_not_rev(self):
        """Test not_rev function."""
        assert project.not_rev("abc123") == "^abc123"

    def test_sq(self):
        """Test sq function for shell quoting."""
        assert project.sq("test") == "'test'"
        assert project.sq("test's") == "'test'''s'"


@pytest.mark.unit
class TestAnnotationClass:
    """Test Annotation class."""

    def test_annotation_init(self):
        """Test Annotation initialization."""
        ann = project.Annotation("name", "value", True)
        assert ann.name == "name"
        assert ann.value == "value"
        assert ann.keep is True

    def test_annotation_equality(self):
        """Test Annotation equality."""
        ann1 = project.Annotation("name", "value", True)
        ann2 = project.Annotation("name", "value", True)
        ann3 = project.Annotation("name", "value", False)

        assert ann1 == ann2
        assert ann1 != ann3
        assert ann1 != "not an annotation"

    def test_annotation_less_than_by_name(self):
        """Test Annotation comparison by name."""
        ann1 = project.Annotation("aaa", "value", True)
        ann2 = project.Annotation("bbb", "value", True)

        assert ann1 < ann2
        assert not ann2 < ann1

    def test_annotation_less_than_by_value(self):
        """Test Annotation comparison by value when names are equal."""
        ann1 = project.Annotation("name", "aaa", True)
        ann2 = project.Annotation("name", "bbb", True)

        assert ann1 < ann2

    def test_annotation_less_than_by_keep(self):
        """Test Annotation comparison by keep when name and value are equal."""
        ann1 = project.Annotation("name", "value", False)
        ann2 = project.Annotation("name", "value", True)

        assert ann1 < ann2

    def test_annotation_less_than_invalid_type(self):
        """Test Annotation comparison with invalid type."""
        ann = project.Annotation("name", "value", True)

        with pytest.raises(ValueError, match="comparison is not between two Annotation objects"):
            ann < "not an annotation"


@pytest.mark.unit
class TestProjectProperties:
    """Test Project class properties and basic methods."""

    def test_shareable_dirs_with_alternates(self):
        """Test shareable_dirs property when using alternates."""
        with mock.patch.object(project, "_ALTERNATES", True):
            proj = mock.Mock(spec=project.Project)
            proj.UseAlternates = True

            # Call the property directly on the class
            result = project.Project.shareable_dirs.fget(proj)
            assert result == ["hooks", "rr-cache"]

    def test_shareable_dirs_without_alternates(self):
        """Test shareable_dirs property when not using alternates."""
        proj = mock.Mock(spec=project.Project)
        proj.UseAlternates = False

        result = project.Project.shareable_dirs.fget(proj)
        assert result == ["hooks", "objects", "rr-cache"]

    def test_use_alternates_property_with_alternates_env(self):
        """Test UseAlternates property with REPO_USE_ALTERNATES=1."""
        with mock.patch.object(project, "_ALTERNATES", True):
            proj = mock.Mock(spec=project.Project)
            proj.manifest = mock.Mock()
            proj.manifest.is_multimanifest = False

            result = project.Project.UseAlternates.fget(proj)
            assert result is True

    def test_use_alternates_property_with_multimanifest(self):
        """Test UseAlternates property with multimanifest."""
        with mock.patch.object(project, "_ALTERNATES", False):
            proj = mock.Mock(spec=project.Project)
            proj.manifest = mock.Mock()
            proj.manifest.is_multimanifest = True

            result = project.Project.UseAlternates.fget(proj)
            assert result is True

    def test_derived_property(self):
        """Test Derived property."""
        proj = mock.Mock(spec=project.Project)
        proj.is_derived = True

        result = project.Project.Derived.fget(proj)
        assert result is True

    def test_exists_property_true(self):
        """Test Exists property when directories exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gitdir = os.path.join(tmpdir, ".git")
            objdir = os.path.join(tmpdir, "objects")
            os.makedirs(gitdir)
            os.makedirs(objdir)

            proj = mock.Mock(spec=project.Project)
            proj.gitdir = gitdir
            proj.objdir = objdir

            result = project.Project.Exists.fget(proj)
            assert result is True

    def test_exists_property_false(self):
        """Test Exists property when directories don't exist."""
        proj = mock.Mock(spec=project.Project)
        proj.gitdir = "/nonexistent/gitdir"
        proj.objdir = "/nonexistent/objdir"

        result = project.Project.Exists.fget(proj)
        assert result is False


@pytest.mark.unit
class TestProjectCurrentBranch:
    """Test Project.CurrentBranch property."""

    def test_current_branch_returns_branch_name(self):
        """Test CurrentBranch returns branch name without refs/heads/ prefix."""
        proj = mock.Mock(spec=project.Project)
        proj.work_git = mock.Mock()
        proj.work_git.GetHead.return_value = "refs/heads/main"

        result = project.Project.CurrentBranch.fget(proj)
        assert result == "main"

    def test_current_branch_detached_head(self):
        """Test CurrentBranch returns None for detached HEAD."""
        proj = mock.Mock(spec=project.Project)
        proj.work_git = mock.Mock()
        proj.work_git.GetHead.return_value = "abc123def456"

        result = project.Project.CurrentBranch.fget(proj)
        assert result is None

    def test_current_branch_no_manifest_exception(self):
        """Test CurrentBranch returns None when NoManifestException is raised."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.work_git = mock.Mock()
        proj.work_git.GetHead.side_effect = error.NoManifestException("/path", "reason")

        result = project.Project.CurrentBranch.fget(proj)
        assert result is None


@pytest.mark.unit
class TestProjectIsDirty:
    """Test Project.IsDirty method."""

    def test_is_dirty_with_cached_changes(self):
        """Test IsDirty returns True when there are cached changes."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.work_git = mock.Mock()
        proj.work_git.update_index = mock.Mock()
        proj.work_git.DiffZ.side_effect = [
            {"file.txt": mock.Mock()},  # diff-index has changes
            {},  # diff-files no changes
        ]
        proj.UntrackedFiles = mock.Mock(return_value=[])

        result = project.Project.IsDirty(proj, consider_untracked=True)
        assert result is True

    def test_is_dirty_with_file_changes(self):
        """Test IsDirty returns True when there are file changes."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.work_git = mock.Mock()
        proj.work_git.update_index = mock.Mock()
        proj.work_git.DiffZ.side_effect = [
            {},  # diff-index no changes
            {"file.txt": mock.Mock()},  # diff-files has changes
        ]
        proj.UntrackedFiles = mock.Mock(return_value=[])

        result = project.Project.IsDirty(proj, consider_untracked=True)
        assert result is True

    def test_is_dirty_with_untracked_files(self):
        """Test IsDirty returns True when there are untracked files."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.work_git = mock.Mock()
        proj.work_git.update_index = mock.Mock()
        proj.work_git.DiffZ.return_value = {}
        proj.UntrackedFiles = mock.Mock(return_value=["untracked.txt"])

        result = project.Project.IsDirty(proj, consider_untracked=True)
        assert result is True

    def test_is_dirty_ignore_untracked(self):
        """Test IsDirty ignores untracked files when consider_untracked=False."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.work_git = mock.Mock()
        proj.work_git.update_index = mock.Mock()
        proj.work_git.DiffZ.return_value = {}
        proj.UntrackedFiles = mock.Mock(return_value=["untracked.txt"])

        result = project.Project.IsDirty(proj, consider_untracked=False)
        assert result is False

    def test_is_dirty_clean(self):
        """Test IsDirty returns False when working directory is clean."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.work_git = mock.Mock()
        proj.work_git.update_index = mock.Mock()
        proj.work_git.DiffZ.return_value = {}
        proj.UntrackedFiles = mock.Mock(return_value=[])

        result = project.Project.IsDirty(proj, consider_untracked=True)
        assert result is False


@pytest.mark.unit
class TestProjectHasChanges:
    """Test Project.HasChanges method."""

    def test_has_changes_true(self):
        """Test HasChanges returns True when there are uncommitted changes."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.UncommitedFiles = mock.Mock(return_value=["file.txt"])

        result = project.Project.HasChanges(proj)
        assert result is True
        proj.UncommitedFiles.assert_called_once_with(get_all=False)

    def test_has_changes_false(self):
        """Test HasChanges returns False when there are no uncommitted changes."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.UncommitedFiles = mock.Mock(return_value=[])

        result = project.Project.HasChanges(proj)
        assert result is False


@pytest.mark.unit
class TestProjectGetRemoteAndBranch:
    """Test Project.GetRemote and GetBranch methods."""

    def test_get_remote_default(self):
        """Test GetRemote returns default remote."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.remote = mock.Mock()
        proj.remote.name = "origin"
        proj.config = mock.Mock()
        proj.config.GetRemote.return_value = mock.Mock()

        project.Project.GetRemote(proj, name=None)
        proj.config.GetRemote.assert_called_once_with("origin")

    def test_get_remote_named(self):
        """Test GetRemote returns named remote."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.remote = mock.Mock()
        proj.config = mock.Mock()
        proj.config.GetRemote.return_value = mock.Mock()

        project.Project.GetRemote(proj, name="upstream")
        proj.config.GetRemote.assert_called_once_with("upstream")

    def test_get_branch(self):
        """Test GetBranch returns branch configuration."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.config = mock.Mock()
        proj.config.GetBranch.return_value = mock.Mock()

        project.Project.GetBranch(proj, "main")
        proj.config.GetBranch.assert_called_once_with("main")


@pytest.mark.unit
class TestProjectRebaseAndCherryPickState:
    """Test Project rebase and cherry-pick state methods."""

    def test_is_rebase_in_progress_rebase_apply(self):
        """Test IsRebaseInProgress detects rebase-apply."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.work_git = mock.Mock()
        proj.work_git.GetDotgitPath.side_effect = lambda x: f"/git/.git/{x}"
        proj.worktree = "/worktree"

        with mock.patch("os.path.exists") as mock_exists:
            mock_exists.side_effect = lambda p: p == "/git/.git/rebase-apply"
            result = project.Project.IsRebaseInProgress(proj)
            assert result is True

    def test_is_rebase_in_progress_rebase_merge(self):
        """Test IsRebaseInProgress detects rebase-merge."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.work_git = mock.Mock()
        proj.work_git.GetDotgitPath.side_effect = lambda x: f"/git/.git/{x}"
        proj.worktree = "/worktree"

        with mock.patch("os.path.exists") as mock_exists:
            mock_exists.side_effect = lambda p: p == "/git/.git/rebase-merge"
            result = project.Project.IsRebaseInProgress(proj)
            assert result is True

    def test_is_rebase_in_progress_dotest(self):
        """Test IsRebaseInProgress detects .dotest."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.work_git = mock.Mock()
        proj.work_git.GetDotgitPath.side_effect = lambda x: f"/git/.git/{x}"
        proj.worktree = "/worktree"

        with mock.patch("os.path.exists") as mock_exists:
            mock_exists.side_effect = lambda p: p == "/worktree/.dotest"
            result = project.Project.IsRebaseInProgress(proj)
            assert result is True

    def test_is_rebase_in_progress_false(self):
        """Test IsRebaseInProgress returns False when no rebase in progress."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.work_git = mock.Mock()
        proj.work_git.GetDotgitPath.side_effect = lambda x: f"/git/.git/{x}"
        proj.worktree = "/worktree"

        with mock.patch("os.path.exists", return_value=False):
            result = project.Project.IsRebaseInProgress(proj)
            assert result is False

    def test_is_cherry_pick_in_progress_true(self):
        """Test IsCherryPickInProgress returns True."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.work_git = mock.Mock()
        proj.work_git.GetDotgitPath.return_value = "/git/.git/CHERRY_PICK_HEAD"

        with mock.patch("os.path.exists", return_value=True):
            result = project.Project.IsCherryPickInProgress(proj)
            assert result is True

    def test_is_cherry_pick_in_progress_false(self):
        """Test IsCherryPickInProgress returns False."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.work_git = mock.Mock()
        proj.work_git.GetDotgitPath.return_value = "/git/.git/CHERRY_PICK_HEAD"

        with mock.patch("os.path.exists", return_value=False):
            result = project.Project.IsCherryPickInProgress(proj)
            assert result is False


@pytest.mark.unit
class TestProjectUserIdentity:
    """Test Project user identity methods."""

    def test_load_user_identity_valid_format(self):
        """Test _LoadUserIdentity with valid format."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj._userident_name = None
        proj._userident_email = None
        proj.bare_git = mock.Mock()
        proj.bare_git.var.return_value = "John Doe <john@example.com> 1234567890 +0000"

        project.Project._LoadUserIdentity(proj)
        assert proj._userident_name == "John Doe"
        assert proj._userident_email == "john@example.com"

    def test_load_user_identity_invalid_format(self):
        """Test _LoadUserIdentity with invalid format."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj._userident_name = None
        proj._userident_email = None
        proj.bare_git = mock.Mock()
        proj.bare_git.var.return_value = "invalid format"

        project.Project._LoadUserIdentity(proj)
        assert proj._userident_name == ""
        assert proj._userident_email == ""


@pytest.mark.unit
class TestProjectBranches:
    """Test Project.GetBranches method."""

    def test_get_branches(self):
        """Test GetBranches returns all branches with metadata."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.CurrentBranch = "main"
        proj._allrefs = {
            "refs/heads/main": "abc123",
            "refs/heads/feature": "def456",
            "refs/published/main": "abc123",
        }

        # Create mock branch objects that will be returned consistently
        branches = {}

        def get_branch_side_effect(name):
            if name not in branches:
                branches[name] = mock.Mock()
            return branches[name]

        proj.GetBranch = mock.Mock(side_effect=get_branch_side_effect)

        result = project.Project.GetBranches(proj)

        assert "main" in result
        assert "feature" in result
        # Verify attributes were set by GetBranches
        assert result["main"].current is True
        assert result["feature"].current is False
        assert result["main"].revision == "abc123"
        assert result["feature"].revision == "def456"
        assert result["main"].published == "abc123"
        assert result["feature"].published is None


@pytest.mark.unit
class TestProjectMatchesGroups:
    """Test Project.MatchesGroups method."""

    def test_matches_groups_all(self):
        """Test MatchesGroups with 'all' group."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.groups = []
        proj.manifest = mock.Mock()
        proj.manifest.default_groups = ["default"]

        result = project.Project.MatchesGroups(proj, ["all"])
        assert result is True

    def test_matches_groups_default(self):
        """Test MatchesGroups with 'default' group."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.groups = []
        proj.manifest = mock.Mock()
        proj.manifest.default_groups = ["default"]

        result = project.Project.MatchesGroups(proj, None)
        assert result is True

    def test_matches_groups_specific(self):
        """Test MatchesGroups with specific group."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.groups = ["group1"]
        proj.manifest = mock.Mock()
        proj.manifest.default_groups = ["default"]

        result = project.Project.MatchesGroups(proj, ["group1"])
        assert result is True

    def test_matches_groups_negation(self):
        """Test MatchesGroups with negated group."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.groups = ["group1"]
        proj.manifest = mock.Mock()
        proj.manifest.default_groups = ["default"]

        result = project.Project.MatchesGroups(proj, ["-group1"])
        assert result is False

    def test_matches_groups_notdefault(self):
        """Test MatchesGroups with 'notdefault' group."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.groups = ["notdefault"]
        proj.manifest = mock.Mock()
        proj.manifest.default_groups = ["default"]

        result = project.Project.MatchesGroups(proj, ["default"])
        assert result is False


@pytest.mark.unit
class TestProjectUncommittedFiles:
    """Test Project.UncommitedFiles method."""

    def test_uncommited_files_with_rebase(self):
        """Test UncommitedFiles includes rebase status."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.work_git = mock.Mock()
        proj.work_git.update_index = mock.Mock()
        proj.work_git.DiffZ.return_value = {}
        proj.IsRebaseInProgress = mock.Mock(return_value=True)
        proj.UntrackedFiles = mock.Mock(return_value=[])

        result = project.Project.UncommitedFiles(proj, get_all=True)
        assert "rebase in progress" in result

    def test_uncommited_files_get_all_false_early_return(self):
        """Test UncommitedFiles with get_all=False returns early."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.work_git = mock.Mock()
        proj.work_git.update_index = mock.Mock()
        proj.work_git.DiffZ.return_value = {"file.txt": mock.Mock()}
        proj.IsRebaseInProgress = mock.Mock(return_value=False)
        proj.UntrackedFiles = mock.Mock(return_value=[])

        result = project.Project.UncommitedFiles(proj, get_all=False)
        assert len(result) > 0
        # Should not call UntrackedFiles since it returns early
        proj.UntrackedFiles.assert_not_called()


@pytest.mark.unit
class TestProjectRelPath:
    """Test Project.RelPath method."""

    def test_rel_path_local(self):
        """Test RelPath with local=True."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.relpath = "project/path"
        proj.manifest = mock.Mock()
        proj.manifest.path_prefix = "prefix"

        result = project.Project.RelPath(proj, local=True)
        assert result == "project/path"

    def test_rel_path_non_local(self):
        """Test RelPath with local=False."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.relpath = "project/path"
        proj.manifest = mock.Mock()
        proj.manifest.path_prefix = "prefix"

        with mock.patch("os.path.join", return_value="prefix/project/path"):
            result = project.Project.RelPath(proj, local=False)
            assert result == "prefix/project/path"


@pytest.mark.unit
class TestProjectSetRevision:
    """Test Project.SetRevision method."""

    def test_set_revision_with_explicit_id(self):
        """Test SetRevision with explicit revisionId parameter."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.revisionExpr = None
        proj.revisionId = None

        with mock.patch("kanon_cli.repo.git_config.IsId", return_value=False):
            project.Project.SetRevision(proj, "main", revisionId="abc123")

        assert proj.revisionExpr == "main"
        assert proj.revisionId == "abc123"

    def test_set_revision_expr_not_id(self):
        """Test SetRevision when revisionExpr is not an ID."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.revisionExpr = None
        proj.revisionId = None

        with mock.patch("kanon_cli.repo.git_config.IsId", return_value=False):
            project.Project.SetRevision(proj, "main", revisionId=None)

        assert proj.revisionExpr == "main"
        assert proj.revisionId is None


@pytest.mark.unit
class TestProjectUpdatePaths:
    """Test Project.UpdatePaths method."""

    def test_update_paths(self):
        """Test UpdatePaths updates all paths."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.manifest = mock.Mock()
        proj.manifest.globalConfig = mock.Mock()

        with (
            mock.patch("kanon_cli.repo.git_config.GitConfig.ForRepository"),
            mock.patch.object(project.Project, "_GitGetByExec"),
            mock.patch("kanon_cli.repo.project.GitRefs"),
        ):
            project.Project.UpdatePaths(proj, "rel/path", "/worktree", "/gitdir", "/objdir")

            assert proj.gitdir == "/gitdir"
            assert proj.objdir == "/objdir"
            assert proj.worktree == "/worktree"
            assert proj.relpath == "rel/path"

    def test_update_paths_no_worktree(self):
        """Test UpdatePaths with None worktree."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.manifest = mock.Mock()
        proj.manifest.globalConfig = mock.Mock()

        with (
            mock.patch("kanon_cli.repo.git_config.GitConfig.ForRepository"),
            mock.patch.object(project.Project, "_GitGetByExec"),
            mock.patch("kanon_cli.repo.project.GitRefs"),
        ):
            project.Project.UpdatePaths(proj, "rel/path", None, "/gitdir", "/objdir")

            assert proj.worktree is None
            assert proj.work_git is None


@pytest.mark.unit
class TestRemoteSpecClass:
    """Test RemoteSpec class."""

    def test_remote_spec_init(self):
        """Test RemoteSpec initialization."""
        spec = project.RemoteSpec(
            name="origin",
            url="https://example.com/repo.git",
            pushUrl="https://example.com/push.git",
            review="https://review.example.com",
            revision="main",
            orig_name="upstream",
            fetchUrl="https://example.com/fetch.git",
        )

        assert spec.name == "origin"
        assert spec.url == "https://example.com/repo.git"
        assert spec.pushUrl == "https://example.com/push.git"
        assert spec.review == "https://review.example.com"
        assert spec.revision == "main"
        assert spec.orig_name == "upstream"
        assert spec.fetchUrl == "https://example.com/fetch.git"


@pytest.mark.unit
class TestDownloadedChangeClass:
    """Test DownloadedChange class."""

    def test_downloaded_change_init(self):
        """Test DownloadedChange initialization."""
        from unittest import mock

        proj = mock.Mock()
        dc = project.DownloadedChange(proj, "base", "12345", "1", "commit123")

        assert dc.project is proj
        assert dc.base == "base"
        assert dc.change_id == "12345"
        assert dc.ps_id == "1"
        assert dc.commit == "commit123"

    def test_downloaded_change_commits_property(self):
        """Test DownloadedChange commits property."""
        from unittest import mock

        proj = mock.Mock()
        proj.bare_git = mock.Mock()
        proj.bare_git.rev_list.return_value = ["abc123 commit message"]

        dc = project.DownloadedChange(proj, "base", "12345", "1", "commit123")

        commits = dc.commits
        assert commits == ["abc123 commit message"]

        # Second call should use cache
        proj.bare_git.rev_list.reset_mock()
        dc.commits
        proj.bare_git.rev_list.assert_not_called()


@pytest.mark.unit
class TestStatusColoringClass:
    """Test StatusColoring class."""

    def test_status_coloring_init(self):
        """Test StatusColoring initialization."""
        from unittest import mock

        config = mock.Mock()
        with mock.patch.object(project.StatusColoring, "printer", return_value=mock.Mock()):
            project.StatusColoring(config)
            # Just verify it doesn't raise


@pytest.mark.unit
class TestDiffColoringClass:
    """Test DiffColoring class."""

    def test_diff_coloring_init(self):
        """Test DiffColoring initialization."""
        from unittest import mock

        config = mock.Mock()
        with mock.patch.object(project.DiffColoring, "printer", return_value=mock.Mock()):
            project.DiffColoring(config)
            # Just verify it doesn't raise


@pytest.mark.unit
class TestSafeExpandPath:
    """Test _SafeExpandPath function."""

    def test_safe_expand_path_basic(self):
        """Test _SafeExpandPath with basic path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = project._SafeExpandPath(tmpdir, "subdir/file.txt")
            expected = os.path.join(tmpdir, "subdir", "file.txt")
            assert result == expected

    def test_safe_expand_path_rejects_dot_dot(self):
        """Test _SafeExpandPath rejects .. in path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(
                error.ManifestInvalidPathError,
                match='".." not allowed in paths',
            ):
                project._SafeExpandPath(tmpdir, "../etc/passwd")

    def test_safe_expand_path_rejects_dot(self):
        """Test _SafeExpandPath rejects . in path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(error.ManifestInvalidPathError, match='"." not allowed in paths'):
                project._SafeExpandPath(tmpdir, "./file.txt")

    def test_safe_expand_path_rejects_symlink_traversal(self):
        """Test _SafeExpandPath rejects symlink traversal."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a symlink
            linkdir = os.path.join(tmpdir, "link")
            targetdir = os.path.join(tmpdir, "target")
            os.makedirs(targetdir)
            os.symlink(targetdir, linkdir)

            with pytest.raises(
                error.ManifestInvalidPathError,
                match="traversing symlinks not allow",
            ):
                project._SafeExpandPath(tmpdir, "link/file.txt")

    def test_safe_expand_path_skipfinal(self):
        """Test _SafeExpandPath with skipfinal=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create directory structure
            subdir = os.path.join(tmpdir, "subdir")
            os.makedirs(subdir)

            result = project._SafeExpandPath(tmpdir, "subdir/file.txt", skipfinal=True)
            expected = os.path.join(tmpdir, "subdir", "file.txt")
            assert result == expected


@pytest.mark.unit
class TestProjectHooksFunction:
    """Test _ProjectHooks function."""

    def test_project_hooks_caches_result(self):
        """Test _ProjectHooks caches the result."""
        from unittest import mock

        # Reset the cache
        project._project_hook_list = None

        with (
            mock.patch("os.path.realpath", return_value="/repo/hooks"),
            mock.patch("os.path.abspath", return_value="/repo/hooks"),
            mock.patch("os.path.dirname", return_value="/repo"),
            mock.patch("kanon_cli.repo.platform_utils.listdir", return_value=["hook1", "hook2"]),
        ):
            result1 = project._ProjectHooks()
            result2 = project._ProjectHooks()

            # Both calls should return the same cached list
            assert result1 is result2


@pytest.mark.unit
class TestProjectSetRevisionId:
    """Test Project.SetRevisionId method."""

    def test_set_revision_id_sets_upstream(self):
        """Test SetRevisionId sets upstream."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.revisionExpr = "main"
        proj.revisionId = None
        proj.upstream = None

        project.Project.SetRevisionId(proj, "abc123")

        assert proj.revisionId == "abc123"
        assert proj.upstream == "main"

    def test_set_revision_id_no_expr(self):
        """Test SetRevisionId with no revisionExpr."""
        from unittest import mock

        proj = mock.Mock(spec=project.Project)
        proj.revisionExpr = None
        proj.revisionId = None

        project.Project.SetRevisionId(proj, "abc123")

        assert proj.revisionId == "abc123"
