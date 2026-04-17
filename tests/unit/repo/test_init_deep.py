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

"""Deep unit tests for subcmds/init.py module."""

from unittest import mock

import pytest

from kanon_cli.repo.error import UpdateManifestError
from kanon_cli.repo.subcmds.init import Init


@pytest.mark.unit
class TestInitSyncManifest:
    """Tests for Init._SyncManifest method."""

    def test_sync_manifest_success(self):
        """Test _SyncManifest successful sync."""
        init_cmd = Init()
        init_cmd.manifest = mock.Mock()
        init_cmd.manifest.manifestProject = mock.Mock()
        init_cmd.manifest.manifestProject.Sync = mock.Mock(return_value=True)

        opt = mock.Mock()
        opt.manifest_depth = None
        opt.manifest_upstream_branch = None
        opt.manifest_url = "https://example.com/manifest"
        opt.manifest_branch = "main"
        opt.standalone_manifest = False
        opt.groups = None
        opt.platform = None
        opt.mirror = False
        opt.dissociate = False
        opt.reference = None
        opt.worktree = False
        opt.submodules = False
        opt.archive = False
        opt.partial_clone = None
        opt.clone_filter = None
        opt.partial_clone_exclude = None
        opt.clone_bundle = True
        opt.git_lfs = False
        opt.use_superproject = None
        opt.verbose = False
        opt.current_branch_only = False
        opt.tags = False
        opt.depth = None
        opt.manifest_name = "default.xml"

        init_cmd.git_event_log = mock.Mock()
        init_cmd._SyncManifest(opt)

        init_cmd.manifest.manifestProject.Sync.assert_called_once()

    def test_sync_manifest_failure(self):
        """Test _SyncManifest raises on sync failure."""
        init_cmd = Init()
        init_cmd.manifest = mock.Mock()
        init_cmd.manifest.manifestProject = mock.Mock()
        init_cmd.manifest.manifestProject.Sync = mock.Mock(return_value=False)

        opt = mock.Mock()
        opt.manifest_depth = None
        opt.manifest_upstream_branch = None
        opt.manifest_url = "https://example.com/manifest"
        opt.manifest_branch = "main"
        opt.standalone_manifest = False
        opt.groups = None
        opt.platform = None
        opt.mirror = False
        opt.dissociate = False
        opt.reference = None
        opt.worktree = False
        opt.submodules = False
        opt.archive = False
        opt.partial_clone = None
        opt.clone_filter = None
        opt.partial_clone_exclude = None
        opt.clone_bundle = True
        opt.git_lfs = False
        opt.use_superproject = None
        opt.verbose = False
        opt.current_branch_only = False
        opt.tags = False
        opt.depth = None
        opt.manifest_name = "default.xml"

        init_cmd.git_event_log = mock.Mock()

        with pytest.raises(UpdateManifestError):
            init_cmd._SyncManifest(opt)


@pytest.mark.unit
class TestInitPrompt:
    """Tests for Init._Prompt method."""

    def test_prompt_with_default(self):
        """Test _Prompt returns default value."""
        init_cmd = Init()

        with mock.patch("sys.stdin.readline", return_value="\n"):
            result = init_cmd._Prompt("Name", "default-value")
            assert result == "default-value"

    def test_prompt_with_user_input(self):
        """Test _Prompt returns user input."""
        init_cmd = Init()

        with mock.patch("sys.stdin.readline", return_value="user-input\n"):
            result = init_cmd._Prompt("Name", "default-value")
            assert result == "user-input"


@pytest.mark.unit
class TestInitShouldConfigureUser:
    """Tests for Init._ShouldConfigureUser method."""

    def test_should_configure_user_no_local_config(self):
        """Test _ShouldConfigureUser when local config missing."""
        init_cmd = Init()
        init_cmd.client = mock.Mock()
        init_cmd.client.globalConfig = mock.Mock()
        init_cmd.client.globalConfig.Has.return_value = False
        init_cmd.manifest = mock.Mock()
        init_cmd.manifest.manifestProject.config.Has.return_value = False

        opt = mock.Mock()
        opt.quiet = True
        opt.verbose = False

        result = init_cmd._ShouldConfigureUser(opt, False)
        assert result is True

    def test_should_configure_user_has_global_config(self):
        """Test _ShouldConfigureUser with global config."""
        init_cmd = Init()
        init_cmd.client = mock.Mock()
        init_cmd.client.globalConfig = mock.Mock()
        init_cmd.client.globalConfig.Has.return_value = True
        init_cmd.client.globalConfig.GetString.side_effect = [
            "John Doe",
            "john@example.com",
        ]
        init_cmd.manifest = mock.Mock()
        init_cmd.manifest.manifestProject.config.Has.return_value = False
        init_cmd.manifest.manifestProject.config.SetString = mock.Mock()

        opt = mock.Mock()
        opt.quiet = True
        opt.verbose = False

        result = init_cmd._ShouldConfigureUser(opt, False)
        assert result is False

    def test_should_configure_user_has_local_config(self):
        """Test _ShouldConfigureUser with local config."""
        init_cmd = Init()
        init_cmd.client = mock.Mock()
        init_cmd.manifest = mock.Mock()
        init_cmd.manifest.manifestProject.config.Has.return_value = True

        opt = mock.Mock()
        opt.quiet = True
        opt.verbose = False

        result = init_cmd._ShouldConfigureUser(opt, False)
        assert result is False


@pytest.mark.unit
class TestInitConfigureUser:
    """Tests for Init._ConfigureUser method."""

    def test_configure_user_accepts_input(self):
        """Test _ConfigureUser accepts user confirmation."""
        init_cmd = Init()
        init_cmd.manifest = mock.Mock()
        init_cmd.manifest.manifestProject = mock.Mock()
        init_cmd.manifest.manifestProject.UserName = "Default Name"
        init_cmd.manifest.manifestProject.UserEmail = "default@example.com"
        init_cmd.manifest.manifestProject.config.SetString = mock.Mock()

        opt = mock.Mock()
        opt.quiet = True

        with mock.patch(
            "sys.stdin.readline",
            side_effect=["New Name\n", "new@example.com\n", "yes\n"],
        ):
            init_cmd._ConfigureUser(opt)

            init_cmd.manifest.manifestProject.config.SetString.assert_any_call("user.name", "New Name")
            init_cmd.manifest.manifestProject.config.SetString.assert_any_call("user.email", "new@example.com")

    def test_configure_user_rejects_and_retries(self):
        """Test _ConfigureUser retries on rejection."""
        init_cmd = Init()
        init_cmd.manifest = mock.Mock()
        init_cmd.manifest.manifestProject = mock.Mock()
        init_cmd.manifest.manifestProject.UserName = "Default Name"
        init_cmd.manifest.manifestProject.UserEmail = "default@example.com"
        init_cmd.manifest.manifestProject.config.SetString = mock.Mock()

        opt = mock.Mock()
        opt.quiet = True

        with mock.patch(
            "sys.stdin.readline",
            side_effect=[
                "Name1\n",
                "email1@example.com\n",
                "no\n",
                "Name2\n",
                "email2@example.com\n",
                "y\n",
            ],
        ):
            init_cmd._ConfigureUser(opt)

            init_cmd.manifest.manifestProject.config.SetString.assert_any_call("user.name", "Name2")
            init_cmd.manifest.manifestProject.config.SetString.assert_any_call("user.email", "email2@example.com")


@pytest.mark.unit
class TestInitHasColorSet:
    """Tests for Init._HasColorSet method."""

    def test_has_color_set_true(self):
        """Test _HasColorSet returns True when color is set."""
        init_cmd = Init()
        gc = mock.Mock()
        gc.Has.return_value = True

        result = init_cmd._HasColorSet(gc)
        assert result is True

    def test_has_color_set_false(self):
        """Test _HasColorSet returns False when color not set."""
        init_cmd = Init()
        gc = mock.Mock()
        gc.Has.return_value = False

        result = init_cmd._HasColorSet(gc)
        assert result is False


@pytest.mark.unit
class TestInitConfigureColor:
    """Tests for Init._ConfigureColor method."""

    def test_configure_color_enabled(self):
        """Test _ConfigureColor enables color."""
        init_cmd = Init()
        init_cmd.client = mock.Mock()
        init_cmd.client.globalConfig = mock.Mock()
        init_cmd.client.globalConfig.Has.return_value = False
        init_cmd.client.globalConfig.SetString = mock.Mock()

        with mock.patch("sys.stdin.readline", return_value="yes\n"):
            init_cmd._ConfigureColor()

            init_cmd.client.globalConfig.SetString.assert_called_with("color.ui", "auto")

    def test_configure_color_disabled(self):
        """Test _ConfigureColor does not enable color."""
        init_cmd = Init()
        init_cmd.client = mock.Mock()
        init_cmd.client.globalConfig = mock.Mock()
        init_cmd.client.globalConfig.Has.return_value = False
        init_cmd.client.globalConfig.SetString = mock.Mock()

        with mock.patch("sys.stdin.readline", return_value="no\n"):
            init_cmd._ConfigureColor()

            init_cmd.client.globalConfig.SetString.assert_not_called()

    def test_configure_color_already_set(self):
        """Test _ConfigureColor skips when already set."""
        init_cmd = Init()
        init_cmd.client = mock.Mock()
        init_cmd.client.globalConfig = mock.Mock()
        init_cmd.client.globalConfig.Has.return_value = True

        init_cmd._ConfigureColor()
        # Should return early without calling SetString


@pytest.mark.unit
class TestInitDisplayResult:
    """Tests for Init._DisplayResult method."""

    def test_display_result_normal(self):
        """Test _DisplayResult for normal init."""
        init_cmd = Init()
        init_cmd.manifest = mock.Mock()
        init_cmd.manifest.IsMirror = False
        init_cmd.manifest.topdir = "/workspace/repo"

        with mock.patch("os.getcwd", return_value="/workspace/repo"):
            init_cmd._DisplayResult()

    def test_display_result_mirror(self):
        """Test _DisplayResult for mirror init."""
        init_cmd = Init()
        init_cmd.manifest = mock.Mock()
        init_cmd.manifest.IsMirror = True
        init_cmd.manifest.topdir = "/workspace/mirror"

        with mock.patch("os.getcwd", return_value="/workspace/mirror"):
            init_cmd._DisplayResult()

    def test_display_result_wrong_directory(self):
        """Test _DisplayResult when in wrong directory."""
        init_cmd = Init()
        init_cmd.manifest = mock.Mock()
        init_cmd.manifest.IsMirror = False
        init_cmd.manifest.topdir = "/workspace/repo"

        with mock.patch("os.getcwd", return_value="/other/directory"):
            init_cmd._DisplayResult()


@pytest.mark.unit
class TestInitValidateOptions:
    """Tests for Init.ValidateOptions method."""


class TestInitExecute:
    """Tests for Init.Execute method."""
