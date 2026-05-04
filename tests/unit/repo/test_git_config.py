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

"""Unittests for the git_config.py module."""

import os
import tempfile
import unittest

import pytest

from kanon_cli.repo import git_config


def fixture(*paths):
    """Return a path relative to test/fixtures."""
    return os.path.join(os.path.dirname(__file__), "fixtures", *paths)


class GitConfigReadOnlyTests(unittest.TestCase):
    """Read-only tests of the GitConfig class."""

    def setUp(self):
        """Create a GitConfig object using the test.gitconfig fixture."""
        config_fixture = fixture("test.gitconfig")
        self.config = git_config.GitConfig(config_fixture)

    def test_GetString_with_empty_config_values(self):
        """
        Test config entries with no value.

        [section]
            empty

        """
        val = self.config.GetString("section.empty")
        self.assertEqual(val, None)

    def test_GetString_with_true_value(self):
        """
        Test config entries with a string value.

        [section]
            nonempty = true

        """
        val = self.config.GetString("section.nonempty")
        self.assertEqual(val, "true")

    def test_GetString_from_missing_file(self):
        """
        Test missing config file
        """
        config_fixture = fixture("not.present.gitconfig")
        config = git_config.GitConfig(config_fixture)
        val = config.GetString("empty")
        self.assertEqual(val, None)

    def test_GetBoolean_undefined(self):
        """Test GetBoolean on key that doesn't exist."""
        self.assertIsNone(self.config.GetBoolean("section.missing"))

    def test_GetBoolean_invalid(self):
        """Test GetBoolean on invalid boolean value."""
        self.assertIsNone(self.config.GetBoolean("section.boolinvalid"))

    def test_GetBoolean_true(self):
        """Test GetBoolean on valid true boolean."""
        self.assertTrue(self.config.GetBoolean("section.booltrue"))

    def test_GetBoolean_false(self):
        """Test GetBoolean on valid false boolean."""
        self.assertFalse(self.config.GetBoolean("section.boolfalse"))

    def test_GetInt_undefined(self):
        """Test GetInt on key that doesn't exist."""
        self.assertIsNone(self.config.GetInt("section.missing"))

    def test_GetInt_invalid(self):
        """Test GetInt on invalid integer value."""
        self.assertIsNone(self.config.GetBoolean("section.intinvalid"))

    def test_GetInt_valid(self):
        """Test GetInt on valid integers."""
        TESTS = (
            ("inthex", 16),
            ("inthexk", 16384),
            ("int", 10),
            ("intk", 10240),
            ("intm", 10485760),
            ("intg", 10737418240),
        )
        for key, value in TESTS:
            self.assertEqual(value, self.config.GetInt(f"section.{key}"))


class GitConfigReadWriteTests(unittest.TestCase):
    """Read/write tests of the GitConfig class."""

    def setUp(self):
        self.tmpfile = tempfile.NamedTemporaryFile()
        self.config = self.get_config()

    def get_config(self):
        """Get a new GitConfig instance."""
        return git_config.GitConfig(self.tmpfile.name)

    def test_SetString(self):
        """Test SetString behavior."""
        # Set a value.
        self.assertIsNone(self.config.GetString("foo.bar"))
        self.config.SetString("foo.bar", "val")
        self.assertEqual("val", self.config.GetString("foo.bar"))

        # Make sure the value was actually written out.
        config = self.get_config()
        self.assertEqual("val", config.GetString("foo.bar"))

        # Update the value.
        self.config.SetString("foo.bar", "valll")
        self.assertEqual("valll", self.config.GetString("foo.bar"))
        config = self.get_config()
        self.assertEqual("valll", config.GetString("foo.bar"))

        # Delete the value.
        self.config.SetString("foo.bar", None)
        self.assertIsNone(self.config.GetString("foo.bar"))
        config = self.get_config()
        self.assertIsNone(config.GetString("foo.bar"))

    def test_SetBoolean(self):
        """Test SetBoolean behavior."""
        # Set a true value.
        self.assertIsNone(self.config.GetBoolean("foo.bar"))
        for val in (True, 1):
            self.config.SetBoolean("foo.bar", val)
            self.assertTrue(self.config.GetBoolean("foo.bar"))

        # Make sure the value was actually written out.
        config = self.get_config()
        self.assertTrue(config.GetBoolean("foo.bar"))
        self.assertEqual("true", config.GetString("foo.bar"))

        # Set a false value.
        for val in (False, 0):
            self.config.SetBoolean("foo.bar", val)
            self.assertFalse(self.config.GetBoolean("foo.bar"))

        # Make sure the value was actually written out.
        config = self.get_config()
        self.assertFalse(config.GetBoolean("foo.bar"))
        self.assertEqual("false", config.GetString("foo.bar"))

        # Delete the value.
        self.config.SetBoolean("foo.bar", None)
        self.assertIsNone(self.config.GetBoolean("foo.bar"))
        config = self.get_config()
        self.assertIsNone(config.GetBoolean("foo.bar"))

    def test_GetSyncAnalysisStateData(self):
        """Test config entries with a sync state analysis data."""
        superproject_logging_data = {}
        superproject_logging_data["test"] = False
        options = type("options", (object,), {})()
        options.verbose = "true"
        options.mp_update = "false"
        TESTS = (
            ("superproject.test", "false"),
            ("options.verbose", "true"),
            ("options.mpupdate", "false"),
            ("main.version", "1"),
        )
        self.config.UpdateSyncAnalysisState(options, superproject_logging_data)
        sync_data = self.config.GetSyncAnalysisStateData()
        for key, value in TESTS:
            self.assertEqual(sync_data[f"{git_config.SYNC_STATE_PREFIX}{key}"], value)
        self.assertTrue(sync_data[f"{git_config.SYNC_STATE_PREFIX}main.synctime"])


# Additional comprehensive tests below


@pytest.mark.unit
class TestGitConfigExtended(unittest.TestCase):
    """Extended tests for GitConfig class."""

    def setUp(self):
        self.tmpfile = tempfile.NamedTemporaryFile()
        self.config = git_config.GitConfig(self.tmpfile.name)

    def test_Has_with_existing_key(self):
        """Test Has() with a key that exists."""
        self.config.SetString("test.key", "value")
        self.assertTrue(self.config.Has("test.key"))

    def test_Has_with_missing_key(self):
        """Test Has() with a key that doesn't exist."""
        self.assertFalse(self.config.Has("missing.key"))

    def test_Has_with_defaults(self):
        """Test Has() checks defaults when include_defaults=True."""
        defaults_tmpfile = tempfile.NamedTemporaryFile()
        defaults = git_config.GitConfig(defaults_tmpfile.name)
        defaults.SetString("default.key", "value")

        config = git_config.GitConfig(self.tmpfile.name, defaults=defaults)
        self.assertTrue(config.Has("default.key", include_defaults=True))
        self.assertFalse(config.Has("default.key", include_defaults=False))

    def test_GetString_with_defaults(self):
        """Test GetString() falls back to defaults."""
        defaults_tmpfile = tempfile.NamedTemporaryFile()
        defaults = git_config.GitConfig(defaults_tmpfile.name)
        defaults.SetString("default.key", "default_value")

        config = git_config.GitConfig(self.tmpfile.name, defaults=defaults)
        self.assertEqual(config.GetString("default.key"), "default_value")

    def test_GetString_all_keys(self):
        """Test GetString() with all_keys=True returns list."""
        self.config.SetString("multi.key", ["val1", "val2", "val3"])
        result = self.config.GetString("multi.key", all_keys=True)
        self.assertEqual(result, ["val1", "val2", "val3"])

    def test_SetString_with_list(self):
        """Test SetString() with list values."""
        self.config.SetString("list.key", ["a", "b", "c"])
        result = self.config.GetString("list.key", all_keys=True)
        self.assertEqual(result, ["a", "b", "c"])

    def test_SetString_with_empty_list(self):
        """Test SetString() with empty list deletes the key."""
        self.config.SetString("test.key", "value")
        self.config.SetString("test.key", [])
        self.assertIsNone(self.config.GetString("test.key"))

    def test_SetString_with_single_item_list(self):
        """Test SetString() with single-item list."""
        self.config.SetString("test.key", ["single"])
        self.assertEqual(self.config.GetString("test.key"), "single")

    def test_GetInt_with_hex(self):
        """Test GetInt() with hexadecimal values."""
        self.config.SetString("test.hex", "0x10")
        self.assertEqual(self.config.GetInt("test.hex"), 16)

    def test_GetInt_with_k_suffix(self):
        """Test GetInt() with 'k' suffix."""
        self.config.SetString("test.k", "10k")
        self.assertEqual(self.config.GetInt("test.k"), 10240)

    def test_GetInt_with_m_suffix(self):
        """Test GetInt() with 'm' suffix."""
        self.config.SetString("test.m", "5m")
        self.assertEqual(self.config.GetInt("test.m"), 5242880)

    def test_GetInt_with_g_suffix(self):
        """Test GetInt() with 'g' suffix."""
        self.config.SetString("test.g", "2g")
        self.assertEqual(self.config.GetInt("test.g"), 2147483648)

    def test_GetInt_with_invalid_value(self):
        """Test GetInt() with invalid value returns None."""
        self.config.SetString("test.invalid", "notanumber")
        self.assertIsNone(self.config.GetInt("test.invalid"))

    def test_DumpConfigDict(self):
        """Test DumpConfigDict() returns all config entries."""
        self.config.SetString("a.b", "value1")
        self.config.SetString("c.d", "value2")
        result = self.config.DumpConfigDict()
        self.assertIn("a.b", result)
        self.assertIn("c.d", result)
        self.assertEqual(result["a.b"], "value1")
        self.assertEqual(result["c.d"], "value2")

    def test_ClearCache(self):
        """Test ClearCache() clears internal cache."""
        self.config.SetString("test.key", "value")
        self.assertEqual(self.config.GetString("test.key"), "value")
        self.config.ClearCache()
        # After clearing cache, it should re-read from file
        self.assertEqual(self.config.GetString("test.key"), "value")

    def test_GetSubSections(self):
        """Test GetSubSections() returns subsections."""
        self.config.SetString("section.sub1.key", "val1")
        self.config.SetString("section.sub2.key", "val2")
        subsections = self.config.GetSubSections("section")
        self.assertIn("sub1", subsections)
        self.assertIn("sub2", subsections)

    def test_HasSection_with_subsection(self):
        """Test HasSection() with subsection."""
        self.config.SetString("sect.subsect.key", "value")
        self.assertTrue(self.config.HasSection("sect", "subsect"))
        self.assertFalse(self.config.HasSection("sect", "missing"))

    def test_HasSection_without_subsection(self):
        """Test HasSection() without subsection."""
        self.config.SetString("sect.key", "value")
        self.assertTrue(self.config.HasSection("sect", ""))

    def test_UrlInsteadOf(self):
        """Test UrlInsteadOf() URL rewriting."""
        self.config.SetString("url.https://new.com/.insteadof", "https://old.com/")
        result = self.config.UrlInsteadOf("https://old.com/repo.git")
        self.assertEqual(result, "https://new.com/repo.git")

    def test_UrlInsteadOf_no_match(self):
        """Test UrlInsteadOf() with no matching insteadof."""
        result = self.config.UrlInsteadOf("https://example.com/repo.git")
        self.assertEqual(result, "https://example.com/repo.git")


@pytest.mark.unit
class TestRefSpec(unittest.TestCase):
    """Tests for RefSpec class."""

    def test_FromString_without_force(self):
        """Test RefSpec.FromString() without force prefix."""
        spec = git_config.RefSpec.FromString("refs/heads/*:refs/remotes/origin/*")
        self.assertFalse(spec.forced)
        self.assertEqual(spec.src, "refs/heads/*")
        self.assertEqual(spec.dst, "refs/remotes/origin/*")

    def test_FromString_with_force(self):
        """Test RefSpec.FromString() with force prefix."""
        spec = git_config.RefSpec.FromString("+refs/heads/*:refs/remotes/origin/*")
        self.assertTrue(spec.forced)
        self.assertEqual(spec.src, "refs/heads/*")
        self.assertEqual(spec.dst, "refs/remotes/origin/*")

    def test_SourceMatches_exact(self):
        """Test RefSpec.SourceMatches() with exact match."""
        spec = git_config.RefSpec(False, "refs/heads/main", "refs/remotes/origin/main")
        self.assertTrue(spec.SourceMatches("refs/heads/main"))
        self.assertFalse(spec.SourceMatches("refs/heads/dev"))

    def test_SourceMatches_wildcard(self):
        """Test RefSpec.SourceMatches() with wildcard."""
        spec = git_config.RefSpec(False, "refs/heads/*", "refs/remotes/origin/*")
        self.assertTrue(spec.SourceMatches("refs/heads/main"))
        self.assertTrue(spec.SourceMatches("refs/heads/dev"))
        self.assertFalse(spec.SourceMatches("refs/tags/v1"))

    def test_DestMatches_exact(self):
        """Test RefSpec.DestMatches() with exact match."""
        spec = git_config.RefSpec(False, "refs/heads/main", "refs/remotes/origin/main")
        self.assertTrue(spec.DestMatches("refs/remotes/origin/main"))
        self.assertFalse(spec.DestMatches("refs/remotes/origin/dev"))

    def test_DestMatches_wildcard(self):
        """Test RefSpec.DestMatches() with wildcard."""
        spec = git_config.RefSpec(False, "refs/heads/*", "refs/remotes/origin/*")
        self.assertTrue(spec.DestMatches("refs/remotes/origin/main"))
        self.assertTrue(spec.DestMatches("refs/remotes/origin/dev"))

    def test_MapSource_wildcard(self):
        """Test RefSpec.MapSource() with wildcard mapping."""
        spec = git_config.RefSpec(False, "refs/heads/*", "refs/remotes/origin/*")
        result = spec.MapSource("refs/heads/feature/branch")
        self.assertEqual(result, "refs/remotes/origin/feature/branch")

    def test_MapSource_exact(self):
        """Test RefSpec.MapSource() with exact mapping."""
        spec = git_config.RefSpec(False, "refs/heads/main", "refs/remotes/origin/main")
        result = spec.MapSource("refs/heads/main")
        self.assertEqual(result, "refs/remotes/origin/main")

    def test_str_forced(self):
        """Test RefSpec.__str__() with forced spec."""
        spec = git_config.RefSpec(True, "refs/heads/*", "refs/remotes/origin/*")
        self.assertEqual(str(spec), "+refs/heads/*:refs/remotes/origin/*")

    def test_str_not_forced(self):
        """Test RefSpec.__str__() without forced spec."""
        spec = git_config.RefSpec(False, "refs/heads/*", "refs/remotes/origin/*")
        self.assertEqual(str(spec), "refs/heads/*:refs/remotes/origin/*")


@pytest.mark.unit
class TestRemote(unittest.TestCase):
    """Tests for Remote class."""

    def setUp(self):
        self.tmpfile = tempfile.NamedTemporaryFile()
        self.config = git_config.GitConfig(self.tmpfile.name)

    def test_GetRemote_creates_remote(self):
        """Test GetRemote() creates Remote object."""
        self.config.SetString("remote.origin.url", "https://example.com/repo.git")
        remote = self.config.GetRemote("origin")
        self.assertEqual(remote.name, "origin")
        self.assertEqual(remote.url, "https://example.com/repo.git")

    def test_GetRemote_caches_remote(self):
        """Test GetRemote() caches Remote objects."""
        remote1 = self.config.GetRemote("origin")
        remote2 = self.config.GetRemote("origin")
        self.assertIs(remote1, remote2)

    def test_Remote_pushUrl(self):
        """Test Remote.pushUrl property."""
        self.config.SetString("remote.origin.url", "https://example.com/repo.git")
        self.config.SetString("remote.origin.pushurl", "https://push.example.com/repo.git")
        remote = self.config.GetRemote("origin")
        self.assertEqual(remote.pushUrl, "https://push.example.com/repo.git")

    def test_Remote_review(self):
        """Test Remote.review property."""
        self.config.SetString("remote.origin.url", "https://example.com/repo.git")
        self.config.SetString("remote.origin.review", "https://review.example.com")
        remote = self.config.GetRemote("origin")
        self.assertEqual(remote.review, "https://review.example.com")

    def test_Remote_projectname(self):
        """Test Remote.projectname property."""
        self.config.SetString("remote.origin.url", "https://example.com/repo.git")
        self.config.SetString("remote.origin.projectname", "myproject")
        remote = self.config.GetRemote("origin")
        self.assertEqual(remote.projectname, "myproject")

    def test_Remote_fetch(self):
        """Test Remote.fetch property returns RefSpec list."""
        self.config.SetString("remote.origin.url", "https://example.com/repo.git")
        self.config.SetString("remote.origin.fetch", ["+refs/heads/*:refs/remotes/origin/*"])
        remote = self.config.GetRemote("origin")
        self.assertEqual(len(remote.fetch), 1)
        self.assertIsInstance(remote.fetch[0], git_config.RefSpec)

    def test_Remote_WritesTo_true(self):
        """Test Remote.WritesTo() returns True for matching ref."""
        self.config.SetString("remote.origin.url", "https://example.com/repo.git")
        self.config.SetString("remote.origin.fetch", ["+refs/heads/*:refs/remotes/origin/*"])
        remote = self.config.GetRemote("origin")
        self.assertTrue(remote.WritesTo("refs/remotes/origin/main"))

    def test_Remote_WritesTo_false(self):
        """Test Remote.WritesTo() returns False for non-matching ref."""
        self.config.SetString("remote.origin.url", "https://example.com/repo.git")
        self.config.SetString("remote.origin.fetch", ["+refs/heads/*:refs/remotes/origin/*"])
        remote = self.config.GetRemote("origin")
        self.assertFalse(remote.WritesTo("refs/remotes/other/main"))

    def test_Remote_ToLocal_with_id(self):
        """Test Remote.ToLocal() with commit ID."""
        self.config.SetString("remote.origin.url", "https://example.com/repo.git")
        remote = self.config.GetRemote("origin")
        commit_id = "a" * 40
        self.assertEqual(remote.ToLocal(commit_id), commit_id)

    def test_Remote_ToLocal_with_dot_name(self):
        """Test Remote.ToLocal() with dot remote name."""
        self.config.SetString("remote...url", "https://example.com/repo.git")
        remote = self.config.GetRemote(".")
        self.assertEqual(remote.ToLocal("main"), "main")

    def test_Remote_ResetFetch_mirror(self):
        """Test Remote.ResetFetch() with mirror=True."""
        self.config.SetString("remote.origin.url", "https://example.com/repo.git")
        remote = self.config.GetRemote("origin")
        remote.ResetFetch(mirror=True)
        self.assertEqual(len(remote.fetch), 1)
        self.assertEqual(remote.fetch[0].dst, "refs/heads/*")

    def test_Remote_ResetFetch_no_mirror(self):
        """Test Remote.ResetFetch() with mirror=False."""
        self.config.SetString("remote.origin.url", "https://example.com/repo.git")
        remote = self.config.GetRemote("origin")
        remote.ResetFetch(mirror=False)
        self.assertEqual(len(remote.fetch), 1)
        self.assertEqual(remote.fetch[0].dst, "refs/remotes/origin/*")

    def test_Remote_Save(self):
        """Test Remote.Save() writes config."""
        self.config.SetString("remote.origin.url", "https://example.com/repo.git")
        remote = self.config.GetRemote("origin")
        remote.projectname = "testproject"
        remote.review = "https://review.example.com"
        remote.Save()

        # Re-read to verify
        config2 = git_config.GitConfig(self.tmpfile.name)
        remote2 = config2.GetRemote("origin")
        self.assertEqual(remote2.projectname, "testproject")
        self.assertEqual(remote2.review, "https://review.example.com")


@pytest.mark.unit
class TestBranch(unittest.TestCase):
    """Tests for Branch class."""

    def setUp(self):
        self.tmpfile = tempfile.NamedTemporaryFile()
        self.config = git_config.GitConfig(self.tmpfile.name)

    def test_GetBranch_creates_branch(self):
        """Test GetBranch() creates Branch object."""
        self.config.SetString("branch.main.merge", "refs/heads/main")
        branch = self.config.GetBranch("main")
        self.assertEqual(branch.name, "main")
        self.assertEqual(branch.merge, "refs/heads/main")

    def test_GetBranch_caches_branch(self):
        """Test GetBranch() caches Branch objects."""
        branch1 = self.config.GetBranch("main")
        branch2 = self.config.GetBranch("main")
        self.assertIs(branch1, branch2)

    def test_Branch_with_remote(self):
        """Test Branch with remote configured."""
        self.config.SetString("remote.origin.url", "https://example.com/repo.git")
        self.config.SetString("branch.main.remote", "origin")
        self.config.SetString("branch.main.merge", "refs/heads/main")
        branch = self.config.GetBranch("main")
        self.assertIsNotNone(branch.remote)
        self.assertEqual(branch.remote.name, "origin")

    def test_Branch_without_remote(self):
        """Test Branch without remote configured."""
        self.config.SetString("branch.main.merge", "refs/heads/main")
        branch = self.config.GetBranch("main")
        self.assertIsNone(branch.remote)

    def test_Branch_LocalMerge_with_remote(self):
        """Test Branch.LocalMerge with remote."""
        self.config.SetString("remote.origin.url", "https://example.com/repo.git")
        self.config.SetString("remote.origin.fetch", ["+refs/heads/*:refs/remotes/origin/*"])
        self.config.SetString("branch.main.remote", "origin")
        self.config.SetString("branch.main.merge", "refs/heads/main")
        branch = self.config.GetBranch("main")
        self.assertEqual(branch.LocalMerge, "refs/remotes/origin/main")

    def test_Branch_LocalMerge_without_remote(self):
        """Test Branch.LocalMerge without remote."""
        branch = self.config.GetBranch("main")
        self.assertIsNone(branch.LocalMerge)


@pytest.mark.unit
class TestUtilityFunctions(unittest.TestCase):
    """Tests for utility functions."""

    def test_IsId_valid(self):
        """Test IsId() with valid commit ID."""
        valid_id = "a" * 40
        self.assertTrue(git_config.IsId(valid_id))

    def test_IsId_invalid_length(self):
        """Test IsId() with invalid length."""
        self.assertFalse(git_config.IsId("abc123"))

    def test_IsId_invalid_chars(self):
        """Test IsId() with invalid characters."""
        invalid_id = "g" * 40
        self.assertFalse(git_config.IsId(invalid_id))

    def test_GetSchemeFromUrl_http(self):
        """Test GetSchemeFromUrl() with http URL."""
        url = "http://example.com/repo.git"
        self.assertEqual(git_config.GetSchemeFromUrl(url), "http")

    def test_GetSchemeFromUrl_https(self):
        """Test GetSchemeFromUrl() with https URL."""
        url = "https://example.com/repo.git"
        self.assertEqual(git_config.GetSchemeFromUrl(url), "https")

    def test_GetSchemeFromUrl_ssh(self):
        """Test GetSchemeFromUrl() with ssh URL."""
        url = "ssh://user@example.com/repo.git"
        self.assertEqual(git_config.GetSchemeFromUrl(url), "ssh")

    def test_GetSchemeFromUrl_no_scheme(self):
        """Test GetSchemeFromUrl() with URL without scheme."""
        url = "example.com/repo.git"
        self.assertIsNone(git_config.GetSchemeFromUrl(url))
