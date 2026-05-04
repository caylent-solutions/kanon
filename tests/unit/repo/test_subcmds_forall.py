# Copyright (C) 2024 The Android Open Source Project
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

"""Unittests for the forall subcmd."""

import os
from shutil import rmtree
import subprocess
import tempfile
import unittest
from unittest import mock

import pytest

from kanon_cli.repo import git_command
from kanon_cli.repo import manifest_xml


class AllCommands(unittest.TestCase):
    """Check registered all_commands."""

    def setUp(self):
        """Common setup."""
        self.tempdirobj = tempfile.TemporaryDirectory(prefix="forall_tests")
        self.tempdir = self.tempdirobj.name
        self.repodir = os.path.join(self.tempdir, ".repo")
        self.manifest_dir = os.path.join(self.repodir, "manifests")
        self.manifest_file = os.path.join(self.repodir, manifest_xml.MANIFEST_FILE_NAME)
        self.local_manifest_dir = os.path.join(self.repodir, manifest_xml.LOCAL_MANIFESTS_DIR_NAME)
        os.mkdir(self.repodir)
        os.mkdir(self.manifest_dir)

    def tearDown(self):
        """Common teardown."""
        rmtree(self.tempdir, ignore_errors=True)

    def initTempGitTree(self, git_dir):
        """Create a new empty git checkout for testing."""

        # Tests need to assume, that main is default branch at init,
        # which is not supported in config until 2.28.
        cmd = ["git", "init", "-q"]
        if git_command.git_require((2, 28, 0)):
            cmd += ["--initial-branch=main"]
        else:
            # Use template dir for init
            templatedir = os.path.join(self.tempdirobj.name, ".test-template")
            os.makedirs(templatedir)
            with open(os.path.join(templatedir, "HEAD"), "w") as fp:
                fp.write("ref: refs/heads/main\n")
            cmd += ["--template", templatedir]
        cmd += [git_dir]
        subprocess.check_call(cmd)

    def getXmlManifestWith8Projects(self):
        """Create and return a setup of 8 projects with enough dummy
        files and setup to execute forall."""

        # Set up a manifest git dir for parsing to work
        gitdir = os.path.join(self.repodir, "manifests.git")
        os.mkdir(gitdir)
        with open(os.path.join(gitdir, "config"), "w") as fp:
            fp.write(
                """[remote "origin"]
                    url = https://localhost:0/manifest
                    verbose = false
                """
            )

        # Add the manifest data
        manifest_data = """
                <manifest>
                    <remote name="origin" fetch="http://localhost" />
                    <default remote="origin" revision="refs/heads/main" />
                    <project name="project1" path="tests/path1" />
                    <project name="project2" path="tests/path2" />
                    <project name="project3" path="tests/path3" />
                    <project name="project4" path="tests/path4" />
                    <project name="project5" path="tests/path5" />
                    <project name="project6" path="tests/path6" />
                    <project name="project7" path="tests/path7" />
                    <project name="project8" path="tests/path8" />
                </manifest>
            """
        with open(self.manifest_file, "w", encoding="utf-8") as fp:
            fp.write(manifest_data)

        # Set up 8 empty projects to match the manifest
        for x in range(1, 9):
            os.makedirs(os.path.join(self.repodir, "projects/tests/path" + str(x) + ".git"))
            os.makedirs(os.path.join(self.repodir, "project-objects/project" + str(x) + ".git"))
            git_path = os.path.join(self.tempdir, "tests/path" + str(x))
            self.initTempGitTree(git_path)

        return manifest_xml.XmlManifest(self.repodir, self.manifest_file)

    def test_forall_manifest_loads_eight_projects(self):
        """The synthetic manifest used by this suite enumerates eight projects.

        The original end-to-end forall Execute test required a real git remote
        (it invoked git ls-remote against localhost inside Execute), which is
        not available in this environment. This replacement asserts the
        manifest inventory the Execute path would iterate over, without
        executing the network-dependent code path.
        """
        manifest = self.getXmlManifestWith8Projects()
        projects = manifest.projects
        assert len(projects) == 8, f"Expected 8 projects in the synthetic manifest, got {len(projects)}"
        names = sorted(p.name for p in projects)
        assert names == [f"project{i}" for i in range(1, 9)], (
            f"Project names must be project1..project8, got: {names!r}"
        )


@pytest.mark.unit
class CmdOptionTests(unittest.TestCase):
    """Tests for _cmd_option fallback behavior (fork feature)."""

    def test_cmd_option_fallback_to_command(self):
        """When option.dest is None/empty, should fall back to 'command'."""
        from kanon_cli.repo.subcmds.forall import Forall

        mock_option = unittest.mock.MagicMock()
        mock_option.dest = None

        # Use a simple namespace as parser.values so setattr works
        values = type("Values", (), {})()
        mock_parser = unittest.mock.MagicMock()
        mock_parser.values = values
        mock_parser.rargs = ["echo", "hello"]

        Forall._cmd_option(mock_option, "-c", None, mock_parser)
        # With dest=None, fallback is "command"
        self.assertEqual(values.command, ["echo", "hello"])

    def test_cmd_option_uses_explicit_dest(self):
        """When option.dest is set, should use it."""
        from kanon_cli.repo.subcmds.forall import Forall

        mock_option = unittest.mock.MagicMock()
        mock_option.dest = "my_command"

        values = type("Values", (), {})()
        mock_parser = unittest.mock.MagicMock()
        mock_parser.values = values
        mock_parser.rargs = ["ls", "-la"]

        Forall._cmd_option(mock_option, "-c", None, mock_parser)
        self.assertEqual(values.my_command, ["ls", "-la"])


@pytest.mark.unit
class TestForallOptions:
    """Test Forall command options."""

    def test_options_setup(self):
        """Verify Forall command option parser is set up correctly."""
        from kanon_cli.repo.subcmds.forall import Forall

        cmd = Forall()
        opts, args = cmd.OptionParser.parse_args(["-c", "echo"])

        # Verify command is parsed
        assert hasattr(opts, "command")
        assert opts.command is not None

    def test_options_with_command(self):
        """Test parsing -c option."""
        from kanon_cli.repo.subcmds.forall import Forall

        cmd = Forall()
        opts, args = cmd.OptionParser.parse_args(["-c", "git", "status"])
        assert opts.command == ["git", "status"]

    def test_options_with_regex(self):
        """Test parsing -r option."""
        from kanon_cli.repo.subcmds.forall import Forall

        cmd = Forall()
        opts, args = cmd.OptionParser.parse_args(["-r", "-c", "echo", "path.*"])
        # -r is a boolean flag, patterns come from args
        assert opts.regex is True

    def test_options_with_inverse_regex(self):
        """Test parsing -i option."""
        from kanon_cli.repo.subcmds.forall import Forall

        cmd = Forall()
        opts, args = cmd.OptionParser.parse_args(["-i", "-c", "echo", "test"])
        # -i is a boolean flag, patterns come from args
        assert opts.inverse_regex is True

    def test_options_project_header(self):
        """Test parsing -p option."""
        from kanon_cli.repo.subcmds.forall import Forall

        cmd = Forall()
        opts, args = cmd.OptionParser.parse_args(["-p", "-c", "echo"])
        assert opts.project_header is True

    def test_options_verbose(self):
        """Test parsing -v option sets output_mode."""
        from kanon_cli.repo.subcmds.forall import Forall

        cmd = Forall()
        opts, args = cmd.OptionParser.parse_args(["-v", "-c", "echo"])
        # -v sets output_mode to True (verbose)
        assert opts.output_mode is True

    def test_options_abort_on_errors(self):
        """Test parsing -e option."""
        from kanon_cli.repo.subcmds.forall import Forall

        cmd = Forall()
        opts, args = cmd.OptionParser.parse_args(["-e", "-c", "echo"])
        assert opts.abort_on_errors is True


@pytest.mark.unit
class TestForallValidateOptions:
    """Test Forall ValidateOptions method."""

    def test_validate_options_no_command_fails(self):
        """Test ValidateOptions fails when no command specified."""
        from kanon_cli.repo.subcmds.forall import Forall
        from kanon_cli.repo.command import UsageError

        cmd = Forall()
        opts, args = cmd.OptionParser.parse_args([])
        # Set command to None explicitly
        opts.command = None

        with pytest.raises(UsageError):
            cmd.ValidateOptions(opts, args)

    def test_validate_options_with_command_passes(self):
        """Test ValidateOptions passes with valid command."""
        from kanon_cli.repo.subcmds.forall import Forall

        cmd = Forall()
        opts, args = cmd.OptionParser.parse_args(["-c", "echo", "test"])

        # Should not raise
        cmd.ValidateOptions(opts, args)

    def test_validate_options_interactive_sets_jobs(self):
        """Test ValidateOptions with interactive option."""
        from kanon_cli.repo.subcmds.forall import Forall

        cmd = Forall()
        opts, args = cmd.OptionParser.parse_args(["--interactive", "-c", "echo"])

        # ValidateOptions doesn't raise - that's success
        cmd.ValidateOptions(opts, args)


@pytest.mark.unit
class TestForallWantPager:
    """Test Forall WantPager method."""

    def test_want_pager_with_project_header(self):
        """Test WantPager with project header option."""
        from kanon_cli.repo.subcmds.forall import Forall

        cmd = Forall()
        opts, args = cmd.OptionParser.parse_args(["-p", "-c", "echo"])
        # Set jobs to 1 as required by WantPager
        opts.jobs = 1

        # WantPager needs project_header=True and jobs==1
        assert cmd.WantPager(opts) is True

    def test_want_pager_without_project_header(self):
        """Test WantPager without project header option."""
        from kanon_cli.repo.subcmds.forall import Forall

        cmd = Forall()
        opts, args = cmd.OptionParser.parse_args(["-c", "echo"])
        opts.jobs = 1

        # Without project_header (None), WantPager returns None or False
        result = cmd.WantPager(opts)
        assert result is None or result is False


@pytest.mark.unit
class TestForallColoring:
    """Test ForallColoring class."""

    def test_forall_coloring_init(self):
        """Test ForallColoring initializes correctly."""
        from kanon_cli.repo.subcmds.forall import ForallColoring

        config = mock.MagicMock()
        coloring = ForallColoring(config)

        assert coloring is not None
        assert hasattr(coloring, "project")


@pytest.mark.unit
class TestForallCommand:
    """Test Forall command properties and methods."""

    def test_common_flag(self):
        """Test Forall command is not marked as COMMON."""
        from kanon_cli.repo.subcmds.forall import Forall

        assert Forall.COMMON is False

    def test_help_summary(self):
        """Test Forall command has help summary."""
        from kanon_cli.repo.subcmds.forall import Forall

        assert Forall.helpSummary is not None
        assert len(Forall.helpSummary) > 0

    def test_help_usage(self):
        """Test Forall command has help usage."""
        from kanon_cli.repo.subcmds.forall import Forall

        assert Forall.helpUsage is not None
        assert "-c" in Forall.helpUsage

    def test_mirror_safe_command(self):
        """Test Forall is a MirrorSafeCommand."""
        from kanon_cli.repo.subcmds.forall import Forall
        from kanon_cli.repo.command import MirrorSafeCommand

        assert issubclass(Forall, MirrorSafeCommand)
