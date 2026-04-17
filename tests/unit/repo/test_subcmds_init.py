# Copyright (C) 2020 The Android Open Source Project
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

"""Unittests for the subcmds/init.py module."""

import optparse
import unittest
from unittest import mock

import pytest

from kanon_cli.repo.subcmds import init


class InitCommand(unittest.TestCase):
    """Check registered all_commands."""

    def setUp(self):
        self.cmd = init.Init()

    def test_cli_parser_good(self):
        """Check valid command line options."""
        ARGV = ([],)
        for argv in ARGV:
            opts, args = self.cmd.OptionParser.parse_args(argv)
            self.cmd.ValidateOptions(opts, args)

    def test_cli_parser_bad(self):
        """Check invalid command line options."""
        ARGV = (
            # Too many arguments.
            ["url", "asdf"],
            # Conflicting options.
            ["--mirror", "--archive"],
        )
        for argv in ARGV:
            opts, args = self.cmd.OptionParser.parse_args(argv)
            with self.assertRaises(SystemExit):
                self.cmd.ValidateOptions(opts, args)


class InitExecuteRepoRevGuard(unittest.TestCase):
    """Check that check_repo_rev is skipped when .repo/repo is absent (pipx install)."""

    def _make_opt(self, repo_rev=None, repo_url=None, repo_verify=True, quiet=True):
        opt = mock.MagicMock()
        opt.repo_rev = repo_rev
        opt.repo_url = repo_url
        opt.repo_verify = repo_verify
        opt.quiet = quiet
        opt.worktree = False
        opt.config_name = False
        return opt

    def _make_cmd_with_worktree(self, worktree_path):
        cmd = init.Init()
        cmd.manifest = mock.MagicMock()
        cmd.manifest.repoProject.worktree = worktree_path
        cmd.manifest.repoProject.GetRemote.return_value = mock.MagicMock()
        cmd.manifest.manifestProject.Exists = False
        cmd.git_event_log = mock.MagicMock()
        return cmd

    def test_check_repo_rev_skipped_when_worktree_absent(self):
        """check_repo_rev must not be called when .repo/repo does not exist."""
        cmd = self._make_cmd_with_worktree("/nonexistent/path/.repo/repo")
        opt = self._make_opt(repo_rev="feat/initial-rpm-git-repo")

        with (
            mock.patch("kanon_cli.repo.subcmds.init.Wrapper") as MockWrapper,
            mock.patch("kanon_cli.repo.subcmds.init.git_require", return_value=True),
            mock.patch("kanon_cli.repo.subcmds.init.WrapperDir", return_value="/fake/dir"),
            mock.patch.object(cmd, "_SyncManifest"),
            mock.patch.object(cmd, "_DisplayResult"),
            mock.patch("os.isatty", return_value=False),
            mock.patch("os.path.isdir", return_value=False),
        ):
            wrapper_instance = MockWrapper.return_value
            wrapper_instance.Requirements.from_dir.return_value = mock.MagicMock(
                get_hard_ver=mock.MagicMock(return_value=(2, 10, 0)),
                get_soft_ver=mock.MagicMock(return_value=(2, 10, 0)),
            )

            cmd.Execute(opt, [])

            wrapper_instance.check_repo_rev.assert_not_called()

    def test_check_repo_rev_called_when_worktree_present(self):
        """check_repo_rev must be called when .repo/repo exists as a git dir."""
        with mock.patch("os.path.isdir", return_value=True):
            cmd = self._make_cmd_with_worktree("/existing/.repo/repo")
            opt = self._make_opt(repo_rev="stable")

            with (
                mock.patch("kanon_cli.repo.subcmds.init.Wrapper") as MockWrapper,
                mock.patch("kanon_cli.repo.subcmds.init.git_require", return_value=True),
                mock.patch("kanon_cli.repo.subcmds.init.WrapperDir", return_value="/fake/dir"),
                mock.patch.object(cmd, "_SyncManifest"),
                mock.patch.object(cmd, "_DisplayResult"),
                mock.patch("os.isatty", return_value=False),
            ):
                wrapper_instance = MockWrapper.return_value
                wrapper_instance.Requirements.from_dir.return_value = mock.MagicMock(
                    get_hard_ver=mock.MagicMock(return_value=(2, 10, 0)),
                    get_soft_ver=mock.MagicMock(return_value=(2, 10, 0)),
                )
                wrapper_instance.check_repo_rev.return_value = (
                    "refs/heads/stable",
                    "abc123",
                )

                cmd.Execute(opt, [])

                wrapper_instance.check_repo_rev.assert_called_once_with(
                    "/existing/.repo/repo",
                    "stable",
                    repo_verify=opt.repo_verify,
                    quiet=opt.quiet,
                )

    def test_repo_rev_not_set_skips_check(self):
        """check_repo_rev must not be called when --repo-rev is not provided."""
        cmd = self._make_cmd_with_worktree("/existing/.repo/repo")
        opt = self._make_opt(repo_rev=None)

        with (
            mock.patch("kanon_cli.repo.subcmds.init.Wrapper") as MockWrapper,
            mock.patch("kanon_cli.repo.subcmds.init.git_require", return_value=True),
            mock.patch("kanon_cli.repo.subcmds.init.WrapperDir", return_value="/fake/dir"),
            mock.patch.object(cmd, "_SyncManifest"),
            mock.patch.object(cmd, "_DisplayResult"),
            mock.patch("os.isatty", return_value=False),
            mock.patch("os.path.isdir", return_value=True),
        ):
            wrapper_instance = MockWrapper.return_value
            wrapper_instance.Requirements.from_dir.return_value = mock.MagicMock(
                get_hard_ver=mock.MagicMock(return_value=(2, 10, 0)),
                get_soft_ver=mock.MagicMock(return_value=(2, 10, 0)),
            )

            cmd.Execute(opt, [])

            wrapper_instance.check_repo_rev.assert_not_called()


@pytest.mark.unit
class TestInitOptions:
    """Test Init command options."""

    def test_options_setup(self):
        """Verify Init command option parser is set up correctly."""
        cmd = init.Init()
        p = optparse.OptionParser()
        cmd._Options(p)
        opts, args = p.parse_args([])

        # Verify default option values from multi-manifest group
        assert opts.outer_manifest is True
        assert opts.this_manifest_only is None

    def test_options_no_outer_manifest(self):
        """Test parsing --no-outer-manifest option."""
        cmd = init.Init()
        opts, args = cmd.OptionParser.parse_args(["--no-outer-manifest"])
        assert opts.outer_manifest is False

    def test_options_this_manifest_only(self):
        """Test parsing --this-manifest-only option."""
        cmd = init.Init()
        opts, args = cmd.OptionParser.parse_args(["--this-manifest-only"])
        assert opts.this_manifest_only is True

    def test_options_all_manifests(self):
        """Test parsing --all-manifests option."""
        cmd = init.Init()
        opts, args = cmd.OptionParser.parse_args(["--all-manifests"])
        assert opts.this_manifest_only is False

    def test_registered_environment_options(self):
        """Test _RegisteredEnvironmentOptions returns correct mapping."""
        cmd = init.Init()
        env_opts = cmd._RegisteredEnvironmentOptions()

        assert env_opts == {
            "REPO_MANIFEST_URL": "manifest_url",
            "REPO_MIRROR_LOCATION": "reference",
            "REPO_GIT_LFS": "git_lfs",
        }


@pytest.mark.unit
class TestInitSyncManifest:
    """Test Init command _SyncManifest method."""

    def test_sync_manifest_sets_clone_depth(self):
        """Test _SyncManifest sets manifestProject clone_depth."""
        cmd = init.Init()
        cmd.manifest = mock.MagicMock()
        cmd.manifest.manifestProject.Sync.return_value = True

        opt = mock.MagicMock()
        opt.manifest_depth = 5
        opt.manifest_upstream_branch = "main"

        cmd._SyncManifest(opt)

        assert cmd.manifest.manifestProject.clone_depth == 5
        assert cmd.manifest.manifestProject.upstream == "main"

    def test_sync_manifest_calls_sync_with_options(self):
        """Test _SyncManifest calls manifestProject.Sync with correct options."""
        cmd = init.Init()
        cmd.manifest = mock.MagicMock()
        cmd.manifest.manifestProject.Sync.return_value = True

        opt = mock.MagicMock()
        opt.manifest_depth = 1
        opt.manifest_upstream_branch = "develop"
        opt.manifest_url = "https://example.com/manifest.git"
        opt.manifest_branch = "stable"
        opt.standalone_manifest = False

        cmd._SyncManifest(opt)

        cmd.manifest.manifestProject.Sync.assert_called_once()
        call_kwargs = cmd.manifest.manifestProject.Sync.call_args[1]
        assert call_kwargs["manifest_url"] == "https://example.com/manifest.git"
        assert call_kwargs["manifest_branch"] == "stable"
        assert call_kwargs["standalone_manifest"] is False

    def test_sync_manifest_raises_on_failure(self):
        """Test _SyncManifest raises UpdateManifestError on failure."""
        from kanon_cli.repo.error import UpdateManifestError

        cmd = init.Init()
        cmd.manifest = mock.MagicMock()
        cmd.manifest.manifestProject.Sync.return_value = False

        opt = mock.MagicMock()
        opt.manifest_depth = 1
        opt.manifest_upstream_branch = "main"
        opt.manifest_name = "default.xml"

        with pytest.raises(UpdateManifestError):
            cmd._SyncManifest(opt)


@pytest.mark.unit
class TestInitUserConfiguration:
    """Test Init command user configuration methods."""

    def test_prompt_accepts_default(self):
        """Test _Prompt returns default value when user presses enter."""
        cmd = init.Init()
        with mock.patch("sys.stdin.readline", return_value="\n"):
            result = cmd._Prompt("Name", "Default Name")
            assert result == "Default Name"

    def test_prompt_accepts_new_value(self):
        """Test _Prompt returns new value when user enters text."""
        cmd = init.Init()
        with mock.patch("sys.stdin.readline", return_value="New Name\n"):
            result = cmd._Prompt("Name", "Default Name")
            assert result == "New Name"

    def test_should_configure_user_missing_config(self):
        """Test _ShouldConfigureUser returns True when config missing."""
        cmd = init.Init()
        cmd.client = mock.MagicMock()
        cmd.manifest = mock.MagicMock()

        cmd.client.globalConfig.Has.return_value = False
        cmd.manifest.manifestProject.config.Has.return_value = False

        opt = mock.MagicMock()
        opt.quiet = True

        result = cmd._ShouldConfigureUser(opt, existing_checkout=False)
        assert result is True

    def test_should_configure_user_has_global_config(self):
        """Test _ShouldConfigureUser copies from global config."""
        cmd = init.Init()
        cmd.client = mock.MagicMock()
        cmd.manifest = mock.MagicMock()

        cmd.manifest.manifestProject.config.Has.return_value = False
        cmd.client.globalConfig.Has.return_value = True
        cmd.client.globalConfig.GetString.side_effect = [
            "John Doe",
            "john@example.com",
        ]

        opt = mock.MagicMock()
        opt.quiet = True

        result = cmd._ShouldConfigureUser(opt, existing_checkout=False)
        assert result is False

        cmd.manifest.manifestProject.config.SetString.assert_any_call("user.name", "John Doe")
        cmd.manifest.manifestProject.config.SetString.assert_any_call("user.email", "john@example.com")

    def test_configure_user_sets_name_and_email(self):
        """Test _ConfigureUser sets user name and email."""
        cmd = init.Init()
        cmd.manifest = mock.MagicMock()
        cmd.manifest.manifestProject.UserName = "Old Name"
        cmd.manifest.manifestProject.UserEmail = "old@example.com"

        opt = mock.MagicMock()
        opt.quiet = True

        with mock.patch.object(cmd, "_Prompt") as mock_prompt:
            mock_prompt.side_effect = ["New Name", "new@example.com"]
            with mock.patch("sys.stdin.readline", return_value="yes\n"):
                cmd._ConfigureUser(opt)

        cmd.manifest.manifestProject.config.SetString.assert_any_call("user.name", "New Name")
        cmd.manifest.manifestProject.config.SetString.assert_any_call("user.email", "new@example.com")

    def test_has_color_set_returns_true(self):
        """Test _HasColorSet returns True when color config exists."""
        cmd = init.Init()
        gc = mock.MagicMock()
        gc.Has.return_value = True

        result = cmd._HasColorSet(gc)
        assert result is True

    def test_has_color_set_returns_false(self):
        """Test _HasColorSet returns False when no color config."""
        cmd = init.Init()
        gc = mock.MagicMock()
        gc.Has.return_value = False

        result = cmd._HasColorSet(gc)
        assert result is False


@pytest.mark.unit
class TestInitCommand:
    """Test Init command properties."""

    def test_common_flag(self):
        """Test Init command is marked as COMMON."""
        assert init.Init.COMMON is True

    def test_multi_manifest_support(self):
        """Test Init command supports multi-manifest."""
        assert init.Init.MULTI_MANIFEST_SUPPORT is True

    def test_help_summary(self):
        """Test Init command has help summary."""
        assert init.Init.helpSummary is not None
        assert len(init.Init.helpSummary) > 0

    def test_common_options_disabled(self):
        """Test _CommonOptions is disabled for Init."""
        cmd = init.Init()
        # _CommonOptions should do nothing (disabled for wrapper reuse)
        result = cmd._CommonOptions(None)
        assert result is None
