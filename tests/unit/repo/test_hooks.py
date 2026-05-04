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

"""Unittests for the hooks.py module."""

import os
import unittest
import unittest.mock

import pytest

from kanon_cli.repo import hooks


class RepoHookShebang(unittest.TestCase):
    """Check shebang parsing in RepoHook."""

    def test_no_shebang(self):
        """Lines w/out shebangs should be rejected."""
        DATA = ("", "#\n# foo\n", "# Bad shebang in script\n#!/foo\n")
        for data in DATA:
            self.assertIsNone(hooks.RepoHook._ExtractInterpFromShebang(data))

    def test_direct_interp(self):
        """Lines whose shebang points directly to the interpreter."""
        DATA = (
            ("#!/foo", "/foo"),
            ("#! /foo", "/foo"),
            ("#!/bin/foo ", "/bin/foo"),
            ("#! /usr/foo ", "/usr/foo"),
            ("#! /usr/foo -args", "/usr/foo"),
        )
        for shebang, interp in DATA:
            self.assertEqual(hooks.RepoHook._ExtractInterpFromShebang(shebang), interp)

    def test_env_interp(self):
        """Lines whose shebang launches through `env`."""
        DATA = (
            ("#!/usr/bin/env foo", "foo"),
            ("#!/bin/env foo", "foo"),
            ("#! /bin/env /bin/foo ", "/bin/foo"),
        )
        for shebang, interp in DATA:
            self.assertEqual(hooks.RepoHook._ExtractInterpFromShebang(shebang), interp)


@pytest.mark.unit
class RepoHookInitTests(unittest.TestCase):
    """Tests for RepoHook initialization guard (fork feature)."""

    def test_script_fullpath_set_when_hooks_project_exists(self):
        """_script_fullpath is set when _hooks_project is provided."""
        mock_project = unittest.mock.MagicMock()
        mock_project.worktree = "/fake/worktree"
        hook = hooks.RepoHook(
            hook_type="pre-upload",
            hooks_project=mock_project,
            repo_topdir="/fake/topdir",
            manifest_url="https://example.com/manifest",
        )
        self.assertEqual(
            hook._script_fullpath,
            os.path.join("/fake/worktree", "pre-upload.py"),
        )

    def test_script_fullpath_none_when_no_hooks_project(self):
        """_script_fullpath is None when hooks_project is None."""
        hook = hooks.RepoHook(
            hook_type="pre-upload",
            hooks_project=None,
            repo_topdir="/fake/topdir",
            manifest_url="https://example.com/manifest",
        )
        self.assertIsNone(hook._script_fullpath)

    def test_run_noop_when_no_hooks_project(self):
        """Run should be a no-op (return True) when hooks_project is None."""
        hook = hooks.RepoHook(
            hook_type="pre-upload",
            hooks_project=None,
            repo_topdir="/fake/topdir",
            manifest_url="https://example.com/manifest",
        )
        result = hook.Run(project_list=[], worktree_list=[])
        self.assertTrue(result)

    def test_run_noop_when_bypass_hooks(self):
        """Run should be a no-op (return True) when bypass_hooks is True."""
        hook = hooks.RepoHook(
            hook_type="pre-upload",
            hooks_project=unittest.mock.MagicMock(),
            repo_topdir="/fake/topdir",
            manifest_url="https://example.com/manifest",
            bypass_hooks=True,
        )
        result = hook.Run(project_list=[], worktree_list=[])
        self.assertTrue(result)


@pytest.mark.unit
class RepoHookRunTests(unittest.TestCase):
    """Tests for RepoHook.Run method."""

    def test_run_returns_true_when_hook_not_enabled(self):
        """Run should return True if hook not in enabled_repo_hooks."""
        mock_project = unittest.mock.MagicMock()
        mock_project.worktree = "/fake/worktree"
        mock_project.enabled_repo_hooks = ["post-sync"]
        hook = hooks.RepoHook(
            hook_type="pre-upload",
            hooks_project=mock_project,
            repo_topdir="/fake/topdir",
            manifest_url="https://example.com/manifest",
        )
        result = hook.Run(project_list=[], worktree_list=[])
        self.assertTrue(result)

    def test_run_checks_api_args(self):
        """Run should validate kwargs match expected API."""
        mock_project = unittest.mock.MagicMock()
        mock_project.worktree = "/fake/worktree"
        mock_project.enabled_repo_hooks = ["pre-upload"]
        hook = hooks.RepoHook(
            hook_type="pre-upload",
            hooks_project=mock_project,
            repo_topdir="/fake/topdir",
            manifest_url="https://example.com/manifest",
            bug_url="https://bugs.example.com",
        )
        # Call with wrong kwargs
        result = hook.Run(wrong_arg="value")
        self.assertFalse(result)

    def test_run_returns_false_on_hook_error(self):
        """Run should return False when HookError is raised."""
        from kanon_cli.repo.error import HookError

        mock_project = unittest.mock.MagicMock()
        mock_project.worktree = "/fake/worktree"
        mock_project.enabled_repo_hooks = ["pre-upload"]
        hook = hooks.RepoHook(
            hook_type="pre-upload",
            hooks_project=mock_project,
            repo_topdir="/fake/topdir",
            manifest_url="https://example.com/manifest",
        )
        with unittest.mock.patch.object(hook, "_CheckHook", side_effect=HookError("test error")):
            result = hook.Run(project_list=[], worktree_list=[])
            self.assertFalse(result)

    def test_run_returns_false_on_system_exit(self):
        """Run should return False when SystemExit is raised."""
        mock_project = unittest.mock.MagicMock()
        mock_project.worktree = "/fake/worktree"
        mock_project.enabled_repo_hooks = ["pre-upload"]
        hook = hooks.RepoHook(
            hook_type="pre-upload",
            hooks_project=mock_project,
            repo_topdir="/fake/topdir",
            manifest_url="https://example.com/manifest",
        )
        with unittest.mock.patch.object(hook, "_CheckHook", side_effect=SystemExit(1)):
            result = hook.Run(project_list=[], worktree_list=[])
            self.assertFalse(result)

    def test_run_returns_true_when_ignore_hooks(self):
        """Run should return True if ignore_hooks is set and hook fails."""
        from kanon_cli.repo.error import HookError

        mock_project = unittest.mock.MagicMock()
        mock_project.worktree = "/fake/worktree"
        mock_project.enabled_repo_hooks = ["pre-upload"]
        hook = hooks.RepoHook(
            hook_type="pre-upload",
            hooks_project=mock_project,
            repo_topdir="/fake/topdir",
            manifest_url="https://example.com/manifest",
            ignore_hooks=True,
        )
        with unittest.mock.patch.object(hook, "_CheckHook", side_effect=HookError("test")):
            result = hook.Run(project_list=[], worktree_list=[])
            self.assertTrue(result)


@pytest.mark.unit
class RepoHookCheckHookTests(unittest.TestCase):
    """Tests for RepoHook._CheckHook method."""

    def test_check_hook_raises_when_file_missing(self):
        """_CheckHook should raise HookError if script file doesn't exist."""
        from kanon_cli.repo.error import HookError

        mock_project = unittest.mock.MagicMock()
        mock_project.worktree = "/nonexistent"
        hook = hooks.RepoHook(
            hook_type="pre-upload",
            hooks_project=mock_project,
            repo_topdir="/fake/topdir",
            manifest_url="https://example.com/manifest",
        )
        with self.assertRaises(HookError):
            hook._CheckHook()


@pytest.mark.unit
class RepoHookGetHashTests(unittest.TestCase):
    """Tests for RepoHook._GetHash method."""

    def test_get_hash_calls_rev_parse(self):
        """_GetHash should call work_git.rev_parse(HEAD)."""
        mock_project = unittest.mock.MagicMock()
        mock_project.worktree = "/fake/worktree"
        mock_project.work_git.rev_parse.return_value = "abc123"
        hook = hooks.RepoHook(
            hook_type="pre-upload",
            hooks_project=mock_project,
            repo_topdir="/fake/topdir",
            manifest_url="https://example.com/manifest",
        )
        result = hook._GetHash()
        mock_project.work_git.rev_parse.assert_called_once()
        self.assertEqual(result, "abc123")


@pytest.mark.unit
class RepoHookGetMustVerbTests(unittest.TestCase):
    """Tests for RepoHook._GetMustVerb method."""

    def test_returns_must_when_abort_if_user_denies(self):
        """_GetMustVerb should return 'must' if abort_if_user_denies is True."""
        hook = hooks.RepoHook(
            hook_type="pre-upload",
            hooks_project=None,
            repo_topdir="/fake/topdir",
            manifest_url="https://example.com/manifest",
            abort_if_user_denies=True,
        )
        self.assertEqual(hook._GetMustVerb(), "must")

    def test_returns_should_when_not_abort_if_user_denies(self):
        """_GetMustVerb should return 'should' if abort_if_user_denies is False."""
        hook = hooks.RepoHook(
            hook_type="pre-upload",
            hooks_project=None,
            repo_topdir="/fake/topdir",
            manifest_url="https://example.com/manifest",
            abort_if_user_denies=False,
        )
        self.assertEqual(hook._GetMustVerb(), "should")


@pytest.mark.unit
class RepoHookManifestUrlSecurityTests(unittest.TestCase):
    """Tests for RepoHook._ManifestUrlHasSecureScheme method."""

    def test_https_is_secure(self):
        """HTTPS URLs should be considered secure."""
        hook = hooks.RepoHook(
            hook_type="pre-upload",
            hooks_project=None,
            repo_topdir="/fake/topdir",
            manifest_url="https://example.com/manifest",
        )
        self.assertTrue(hook._ManifestUrlHasSecureScheme())

    def test_ssh_is_secure(self):
        """SSH URLs should be considered secure."""
        hook = hooks.RepoHook(
            hook_type="pre-upload",
            hooks_project=None,
            repo_topdir="/fake/topdir",
            manifest_url="ssh://example.com/manifest",
        )
        self.assertTrue(hook._ManifestUrlHasSecureScheme())

    def test_file_is_secure(self):
        """File URLs should be considered secure."""
        hook = hooks.RepoHook(
            hook_type="pre-upload",
            hooks_project=None,
            repo_topdir="/fake/topdir",
            manifest_url="file:///path/to/manifest",
        )
        self.assertTrue(hook._ManifestUrlHasSecureScheme())

    def test_http_is_not_secure(self):
        """HTTP URLs should not be considered secure."""
        hook = hooks.RepoHook(
            hook_type="pre-upload",
            hooks_project=None,
            repo_topdir="/fake/topdir",
            manifest_url="http://example.com/manifest",
        )
        self.assertFalse(hook._ManifestUrlHasSecureScheme())

    def test_persistent_https_is_secure(self):
        """persistent-https URLs should be considered secure."""
        hook = hooks.RepoHook(
            hook_type="pre-upload",
            hooks_project=None,
            repo_topdir="/fake/topdir",
            manifest_url="persistent-https://example.com/manifest",
        )
        self.assertTrue(hook._ManifestUrlHasSecureScheme())

    def test_sso_is_secure(self):
        """sso URLs should be considered secure."""
        hook = hooks.RepoHook(
            hook_type="pre-upload",
            hooks_project=None,
            repo_topdir="/fake/topdir",
            manifest_url="sso://example.com/manifest",
        )
        self.assertTrue(hook._ManifestUrlHasSecureScheme())

    def test_rpc_is_secure(self):
        """rpc URLs should be considered secure."""
        hook = hooks.RepoHook(
            hook_type="pre-upload",
            hooks_project=None,
            repo_topdir="/fake/topdir",
            manifest_url="rpc://example.com/manifest",
        )
        self.assertTrue(hook._ManifestUrlHasSecureScheme())


@pytest.mark.unit
class RepoHookCheckForHookApprovalTests(unittest.TestCase):
    """Tests for RepoHook._CheckForHookApproval method."""

    def test_uses_manifest_approval_for_secure_url(self):
        """Should use manifest approval for secure URLs."""
        mock_project = unittest.mock.MagicMock()
        hook = hooks.RepoHook(
            hook_type="pre-upload",
            hooks_project=mock_project,
            repo_topdir="/fake/topdir",
            manifest_url="https://example.com/manifest",
        )
        with unittest.mock.patch.object(hook, "_CheckForHookApprovalManifest", return_value=True) as mock_manifest:
            with unittest.mock.patch.object(hook, "_CheckForHookApprovalHash") as mock_hash:
                result = hook._CheckForHookApproval()
                mock_manifest.assert_called_once()
                mock_hash.assert_not_called()
                self.assertTrue(result)

    def test_uses_hash_approval_for_insecure_url(self):
        """Should use hash approval for insecure URLs."""
        mock_project = unittest.mock.MagicMock()
        hook = hooks.RepoHook(
            hook_type="pre-upload",
            hooks_project=mock_project,
            repo_topdir="/fake/topdir",
            manifest_url="http://example.com/manifest",
        )
        with unittest.mock.patch.object(hook, "_CheckForHookApprovalManifest") as mock_manifest:
            with unittest.mock.patch.object(hook, "_CheckForHookApprovalHash", return_value=True) as mock_hash:
                result = hook._CheckForHookApproval()
                mock_manifest.assert_not_called()
                mock_hash.assert_called_once()
                self.assertTrue(result)


@pytest.mark.unit
class RepoHookExtractInterpTests(unittest.TestCase):
    """Additional tests for _ExtractInterpFromShebang."""

    def test_multiline_returns_first_line_only(self):
        """Should only look at first line of multi-line input."""
        data = "#!/usr/bin/python3\nprint('hello')\n"
        result = hooks.RepoHook._ExtractInterpFromShebang(data)
        self.assertEqual(result, "/usr/bin/python3")

    def test_empty_string_returns_none(self):
        """Empty string should return None."""
        result = hooks.RepoHook._ExtractInterpFromShebang("")
        self.assertIsNone(result)

    def test_whitespace_after_shebang(self):
        """Should handle extra whitespace after shebang."""
        result = hooks.RepoHook._ExtractInterpFromShebang("#!   /bin/bash  ")
        self.assertEqual(result, "/bin/bash")


@pytest.mark.unit
class RepoHookExecuteHookTests(unittest.TestCase):
    """Tests for RepoHook._ExecuteHook method."""

    def test_execute_hook_changes_cwd(self):
        """_ExecuteHook should change to repo_topdir."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_project = unittest.mock.MagicMock()
            mock_project.worktree = tmpdir
            script_path = os.path.join(tmpdir, "pre-upload.py")
            with open(script_path, "w") as f:
                f.write("#!/usr/bin/env python3\ndef main(**kwargs):\n    pass\n")
            hook = hooks.RepoHook(
                hook_type="pre-upload",
                hooks_project=mock_project,
                repo_topdir=tmpdir,
                manifest_url="https://example.com/manifest",
            )
            original_cwd = os.getcwd()
            try:
                hook._ExecuteHook(project_list=[], worktree_list=[])
            except Exception:
                pass
            # CWD should be restored
            self.assertEqual(os.getcwd(), original_cwd)

    def test_execute_hook_restores_sys_path(self):
        """_ExecuteHook should restore sys.path after execution."""
        import sys
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_project = unittest.mock.MagicMock()
            mock_project.worktree = tmpdir
            script_path = os.path.join(tmpdir, "pre-upload.py")
            with open(script_path, "w") as f:
                f.write("#!/usr/bin/env python3\ndef main(**kwargs):\n    pass\n")
            hook = hooks.RepoHook(
                hook_type="pre-upload",
                hooks_project=mock_project,
                repo_topdir=tmpdir,
                manifest_url="https://example.com/manifest",
            )
            original_path = sys.path.copy()
            try:
                hook._ExecuteHook(project_list=[], worktree_list=[])
            except Exception:
                pass
            self.assertEqual(sys.path, original_path)


@pytest.mark.unit
class RepoHookFromSubcmdTests(unittest.TestCase):
    """Tests for RepoHook.FromSubcmd class method."""

    def test_from_subcmd_extracts_manifest_fields(self):
        """FromSubcmd should extract fields from manifest."""
        mock_manifest = unittest.mock.MagicMock()
        mock_manifest.repo_hooks_project = unittest.mock.MagicMock()
        mock_manifest.topdir = "/topdir"
        mock_manifest.manifestProject.GetRemote.return_value.url = "https://example.com/manifest"
        mock_manifest.contactinfo.bugurl = "https://bugs.example.com"
        mock_opt = unittest.mock.MagicMock()
        mock_opt.bypass_hooks = False
        mock_opt.allow_all_hooks = False
        mock_opt.ignore_hooks = False

        result = hooks.RepoHook.FromSubcmd(mock_manifest, mock_opt, "pre-upload")
        self.assertIsInstance(result, hooks.RepoHook)
        self.assertEqual(result._hook_type, "pre-upload")


@pytest.mark.unit
class RepoHookAddOptionGroupTests(unittest.TestCase):
    """Tests for RepoHook.AddOptionGroup static method."""

    def test_add_option_group_adds_verify_option(self):
        """AddOptionGroup should add --verify option."""
        from optparse import OptionParser

        parser = OptionParser()
        hooks.RepoHook.AddOptionGroup(parser, "pre-upload")
        # Parse with --verify flag
        args, _ = parser.parse_args(["--verify"])
        self.assertTrue(args.allow_all_hooks)

    def test_add_option_group_adds_no_verify_option(self):
        """AddOptionGroup should add --no-verify option."""
        from optparse import OptionParser

        parser = OptionParser()
        hooks.RepoHook.AddOptionGroup(parser, "pre-upload")
        args, _ = parser.parse_args(["--no-verify"])
        self.assertTrue(args.bypass_hooks)

    def test_add_option_group_adds_ignore_hooks_option(self):
        """AddOptionGroup should add --ignore-hooks option."""
        from optparse import OptionParser

        parser = OptionParser()
        hooks.RepoHook.AddOptionGroup(parser, "pre-upload")
        args, _ = parser.parse_args(["--ignore-hooks"])
        self.assertTrue(args.ignore_hooks)
