# Copyright 2021 The Android Open Source Project
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

"""Unittests for the error.py module."""

import inspect
import pickle
import unittest

import pytest

from kanon_cli.repo import command
from kanon_cli.repo import error
from kanon_cli.repo import fetch
from kanon_cli.repo import git_command
from kanon_cli.repo import project
from kanon_cli.repo.subcmds import all_modules


imports = all_modules + [
    error,
    project,
    git_command,
    fetch,
    command,
]


class PickleTests(unittest.TestCase):
    """Make sure all our custom exceptions can be pickled."""

    def getExceptions(self):
        """Return all our custom exceptions."""
        for entry in imports:
            for name in dir(entry):
                cls = getattr(entry, name)
                if isinstance(cls, type) and issubclass(cls, Exception):
                    yield cls

    def testExceptionLookup(self):
        """Make sure our introspection logic works."""
        classes = list(self.getExceptions())
        self.assertIn(error.HookError, classes)
        # Don't assert the exact number to avoid being a change-detector test.
        self.assertGreater(len(classes), 10)

    def testPickle(self):
        """Try to pickle all the exceptions."""
        for cls in self.getExceptions():
            args = inspect.getfullargspec(cls.__init__).args[1:]
            obj = cls(*args)
            p = pickle.dumps(obj)
            try:
                newobj = pickle.loads(p)
            except Exception as e:  # pylint: disable=broad-except
                self.fail("Class %s is unable to be pickled: %s\nIncomplete super().__init__(...) call?" % (cls, e))
            self.assertIsInstance(newobj, cls)
            self.assertEqual(str(obj), str(newobj))


@pytest.mark.unit
class BaseRepoErrorTests(unittest.TestCase):
    """Tests for BaseRepoError exception."""

    def test_base_repo_error_is_exception(self):
        """BaseRepoError should inherit from Exception."""
        self.assertTrue(issubclass(error.BaseRepoError, Exception))

    def test_base_repo_error_can_be_raised(self):
        """BaseRepoError can be raised."""
        with self.assertRaises(error.BaseRepoError):
            raise error.BaseRepoError("test error")


@pytest.mark.unit
class RepoErrorTests(unittest.TestCase):
    """Tests for RepoError exception."""

    def test_repo_error_inherits_from_base(self):
        """RepoError should inherit from BaseRepoError."""
        self.assertTrue(issubclass(error.RepoError, error.BaseRepoError))

    def test_repo_error_stores_project(self):
        """RepoError should store project parameter."""
        err = error.RepoError("message", project="myproject")
        self.assertEqual(err.project, "myproject")

    def test_repo_error_project_defaults_to_none(self):
        """RepoError project should default to None."""
        err = error.RepoError("message")
        self.assertIsNone(err.project)


@pytest.mark.unit
class RepoExitErrorTests(unittest.TestCase):
    """Tests for RepoExitError exception."""

    def test_repo_exit_error_inherits_from_base(self):
        """RepoExitError should inherit from BaseRepoError."""
        self.assertTrue(issubclass(error.RepoExitError, error.BaseRepoError))

    def test_repo_exit_error_stores_exit_code(self):
        """RepoExitError should store exit_code."""
        err = error.RepoExitError("message", exit_code=42)
        self.assertEqual(err.exit_code, 42)

    def test_repo_exit_error_exit_code_defaults_to_one(self):
        """RepoExitError exit_code should default to 1."""
        err = error.RepoExitError("message")
        self.assertEqual(err.exit_code, 1)

    def test_repo_exit_error_stores_aggregate_errors(self):
        """RepoExitError should store aggregate_errors."""
        errors = [Exception("err1"), Exception("err2")]
        err = error.RepoExitError("message", aggregate_errors=errors)
        self.assertEqual(err.aggregate_errors, errors)

    def test_repo_exit_error_aggregate_errors_defaults_to_none(self):
        """RepoExitError aggregate_errors should default to None."""
        err = error.RepoExitError("message")
        self.assertIsNone(err.aggregate_errors)


@pytest.mark.unit
class RepoUnhandledExceptionErrorTests(unittest.TestCase):
    """Tests for RepoUnhandledExceptionError exception."""

    def test_inherits_from_repo_exit_error(self):
        """RepoUnhandledExceptionError should inherit from RepoExitError."""
        self.assertTrue(issubclass(error.RepoUnhandledExceptionError, error.RepoExitError))

    def test_stores_error(self):
        """RepoUnhandledExceptionError should store error."""
        original_error = ValueError("test")
        err = error.RepoUnhandledExceptionError(original_error)
        self.assertIs(err.error, original_error)


@pytest.mark.unit
class SilentRepoExitErrorTests(unittest.TestCase):
    """Tests for SilentRepoExitError exception."""

    def test_inherits_from_repo_exit_error(self):
        """SilentRepoExitError should inherit from RepoExitError."""
        self.assertTrue(issubclass(error.SilentRepoExitError, error.RepoExitError))


@pytest.mark.unit
class ManifestParseErrorTests(unittest.TestCase):
    """Tests for ManifestParseError exception."""

    def test_inherits_from_repo_exit_error(self):
        """ManifestParseError should inherit from RepoExitError."""
        self.assertTrue(issubclass(error.ManifestParseError, error.RepoExitError))


@pytest.mark.unit
class ManifestInvalidRevisionErrorTests(unittest.TestCase):
    """Tests for ManifestInvalidRevisionError exception."""

    def test_inherits_from_manifest_parse_error(self):
        """ManifestInvalidRevisionError should inherit from ManifestParseError."""
        self.assertTrue(issubclass(error.ManifestInvalidRevisionError, error.ManifestParseError))


@pytest.mark.unit
class ManifestInvalidPathErrorTests(unittest.TestCase):
    """Tests for ManifestInvalidPathError exception."""

    def test_inherits_from_manifest_parse_error(self):
        """ManifestInvalidPathError should inherit from ManifestParseError."""
        self.assertTrue(issubclass(error.ManifestInvalidPathError, error.ManifestParseError))


@pytest.mark.unit
class NoManifestExceptionTests(unittest.TestCase):
    """Tests for NoManifestException exception."""

    def test_inherits_from_repo_exit_error(self):
        """NoManifestException should inherit from RepoExitError."""
        self.assertTrue(issubclass(error.NoManifestException, error.RepoExitError))

    def test_stores_path_and_reason(self):
        """NoManifestException should store path and reason."""
        err = error.NoManifestException("/path", "reason text")
        self.assertEqual(err.path, "/path")
        self.assertEqual(err.reason, "reason text")

    def test_str_returns_reason(self):
        """NoManifestException.__str__ should return reason."""
        err = error.NoManifestException("/path", "reason text")
        self.assertEqual(str(err), "reason text")


@pytest.mark.unit
class EditorErrorTests(unittest.TestCase):
    """Tests for EditorError exception."""

    def test_inherits_from_repo_error(self):
        """EditorError should inherit from RepoError."""
        self.assertTrue(issubclass(error.EditorError, error.RepoError))

    def test_stores_reason(self):
        """EditorError should store reason."""
        err = error.EditorError("editor failed")
        self.assertEqual(err.reason, "editor failed")

    def test_str_returns_reason(self):
        """EditorError.__str__ should return reason."""
        err = error.EditorError("editor failed")
        self.assertEqual(str(err), "editor failed")


@pytest.mark.unit
class GitErrorTests(unittest.TestCase):
    """Tests for GitError exception."""

    def test_inherits_from_repo_error(self):
        """GitError should inherit from RepoError."""
        self.assertTrue(issubclass(error.GitError, error.RepoError))

    def test_stores_message(self):
        """GitError should store message."""
        err = error.GitError("git failed")
        self.assertEqual(err.message, "git failed")

    def test_stores_command_args(self):
        """GitError should store command_args."""
        err = error.GitError("git failed", command_args=["git", "clone"])
        self.assertEqual(err.command_args, ["git", "clone"])

    def test_command_args_defaults_to_none(self):
        """GitError command_args should default to None."""
        err = error.GitError("git failed")
        self.assertIsNone(err.command_args)

    def test_str_returns_message(self):
        """GitError.__str__ should return message."""
        err = error.GitError("git failed")
        self.assertEqual(str(err), "git failed")


@pytest.mark.unit
class GitAuthErrorTests(unittest.TestCase):
    """Tests for GitAuthError exception."""

    def test_inherits_from_repo_exit_error(self):
        """GitAuthError should inherit from RepoExitError."""
        self.assertTrue(issubclass(error.GitAuthError, error.RepoExitError))


@pytest.mark.unit
class UploadErrorTests(unittest.TestCase):
    """Tests for UploadError exception."""

    def test_inherits_from_repo_error(self):
        """UploadError should inherit from RepoError."""
        self.assertTrue(issubclass(error.UploadError, error.RepoError))

    def test_stores_reason(self):
        """UploadError should store reason."""
        err = error.UploadError("upload failed")
        self.assertEqual(err.reason, "upload failed")

    def test_str_returns_reason(self):
        """UploadError.__str__ should return reason."""
        err = error.UploadError("upload failed")
        self.assertEqual(str(err), "upload failed")


@pytest.mark.unit
class DownloadErrorTests(unittest.TestCase):
    """Tests for DownloadError exception."""

    def test_inherits_from_repo_exit_error(self):
        """DownloadError should inherit from RepoExitError."""
        self.assertTrue(issubclass(error.DownloadError, error.RepoExitError))

    def test_stores_reason(self):
        """DownloadError should store reason."""
        err = error.DownloadError("download failed")
        self.assertEqual(err.reason, "download failed")

    def test_str_returns_reason(self):
        """DownloadError.__str__ should return reason."""
        err = error.DownloadError("download failed")
        self.assertEqual(str(err), "download failed")


@pytest.mark.unit
class NoSuchProjectErrorTests(unittest.TestCase):
    """Tests for NoSuchProjectError exception."""

    def test_inherits_from_repo_exit_error(self):
        """NoSuchProjectError should inherit from RepoExitError."""
        self.assertTrue(issubclass(error.NoSuchProjectError, error.RepoExitError))

    def test_stores_name(self):
        """NoSuchProjectError should store name."""
        err = error.NoSuchProjectError(name="myproject")
        self.assertEqual(err.name, "myproject")

    def test_name_defaults_to_none(self):
        """NoSuchProjectError name should default to None."""
        err = error.NoSuchProjectError()
        self.assertIsNone(err.name)

    def test_str_returns_name(self):
        """NoSuchProjectError.__str__ should return name."""
        err = error.NoSuchProjectError(name="myproject")
        self.assertEqual(str(err), "myproject")

    def test_str_returns_default_message_when_no_name(self):
        """NoSuchProjectError.__str__ should return default when name is None."""
        err = error.NoSuchProjectError()
        self.assertEqual(str(err), "in current directory")


@pytest.mark.unit
class HookErrorTests(unittest.TestCase):
    """Tests for HookError exception."""

    def test_inherits_from_repo_error(self):
        """HookError should inherit from RepoError."""
        self.assertTrue(issubclass(error.HookError, error.RepoError))


@pytest.mark.unit
class RepoChangedExceptionTests(unittest.TestCase):
    """Tests for RepoChangedException exception."""

    def test_inherits_from_base_repo_error(self):
        """RepoChangedException should inherit from BaseRepoError."""
        self.assertTrue(issubclass(error.RepoChangedException, error.BaseRepoError))

    def test_stores_extra_args(self):
        """RepoChangedException should store extra_args."""
        err = error.RepoChangedException(extra_args=["--flag"])
        self.assertEqual(err.extra_args, ["--flag"])

    def test_extra_args_defaults_to_empty_list(self):
        """RepoChangedException extra_args should default to empty list."""
        err = error.RepoChangedException()
        self.assertEqual(err.extra_args, [])
